"""
Pluggable SQL Dialects for Query Builder Engine.
================================================
Provides quote escaping, parameter placeholder handling, and dialect-specific
SQL syntax generation for PostgreSQL, Snowflake, Microsoft SQL Server, SQLite, and MySQL.
"""

from __future__ import annotations

import re
from typing import Any

from query_builder.exceptions import DialectError

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
MAX_IDENTIFIER_LENGTH = 128
MAX_ALIAS_LENGTH = 256


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
    pagination_placement: str = "suffix"
    requires_order_by_for_pagination: bool = False
    supports_cte: bool = True
    supports_recursive_cte: bool = True
    supports_materialized_cte: bool = False
    supports_window_functions: bool = True
    supports_window_groups_frame: bool = False
    # LIKE wildcard handling for the contains/starts_with/ends_with operators.
    # ``None`` (default): the bound value is passed through unchanged, so a user
    # value containing ``%`` or ``_`` acts as a wildcard. Dialects verified live
    # set the escape character (and whether it must be declared with ESCAPE).
    avg_template: str = "AVG({})"
    count_distinct_template: str = "COUNT(DISTINCT {})"
    #: keyword between a derived table's ")" and its alias; Oracle rejects ``AS`` there
    subquery_alias_keyword: str = "AS "
    neq_operator: str = "!="  # Drill rejects "!=" ("Bang equal is not allowed")
    like_escape_char: str | None = None
    like_escape_clause: bool = False
    like_special_chars: str = "%_"

    def escape_like(self, value: Any) -> str:
        """Escape LIKE wildcards in a literal substring (no-op if unsupported)."""
        text = str(value)
        esc = self.like_escape_char
        if not esc:
            return text
        for ch in (esc, *self.like_special_chars):
            text = text.replace(ch, esc + ch)
        return text

    def substring_param(self, mode: str, value: Any) -> str:
        """Bound value for contains ("contains") / starts_with ("starts") / ends_with ("ends")."""
        escaped = self.escape_like(value)
        if mode == "contains":
            return f"%{escaped}%"
        return f"{escaped}%" if mode == "starts" else f"%{escaped}"

    def format_substring_match(self, col_ref: str) -> str:
        """Case-insensitive LIKE used by contains/starts_with/ends_with."""
        expr = self.format_ilike(col_ref)
        if self.like_escape_clause and self.like_escape_char:
            expr = f"{expr} ESCAPE '{self.like_escape_char}'"
        return expr

    def format_cte_materialized(self, materialized: bool | None) -> str:
        """Returns MATERIALIZED or NOT MATERIALIZED hint if supported, else empty string."""
        if materialized is None or not getattr(
            self, "supports_materialized_cte", False
        ):
            return ""
        return "MATERIALIZED " if materialized else "NOT MATERIALIZED "

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

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats vector distance calculation expression for a column reference and placeholder."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"L2_DISTANCE({col_ref}, {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"INNER_PRODUCT({col_ref}, {self.placeholder})"
        return f"COSINE_DISTANCE({col_ref}, {self.placeholder})"

    def format_vector_param(self, vector: list[float]) -> Any:
        """Formats a vector list for driver query parameter binding."""
        return str(vector)

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats a basic text matching score expression."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        cases = [
            f"(CASE WHEN {col} LIKE {ph} THEN 1.0 ELSE 0.0 END)" for col in col_refs
        ]
        return f"({' + '.join(cases)})"

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

    def inspect_tables(self, schema_name: str = "public") -> tuple[str, list[Any]]:
        """Convenience alias for inspect_tables_query."""
        return self.inspect_tables_query(schema_name)

    def inspect_columns(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Convenience alias for inspect_columns_query."""
        return self.inspect_columns_query(schema_name, table_name)

    def inspect_primary_keys(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Convenience alias for inspect_primary_keys_query."""
        return self.inspect_primary_keys_query(schema_name, table_name)

    def inspect_foreign_keys(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Convenience alias for inspect_foreign_keys_query."""
        return self.inspect_foreign_keys_query(schema_name, table_name)


class PostgresDialect(BaseDialect):
    """PostgreSQL dialect."""

    name: str = "postgres"
    supports_materialized_cte: bool = True
    supports_window_groups_frame: bool = True
    like_escape_char = "\\"  # PostgreSQL's default LIKE escape

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats pgvector distance operator expression."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"({col_ref} <-> {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"({col_ref} <#> {self.placeholder})"
        return f"({col_ref} <=> {self.placeholder})"

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats PostgreSQL ts_rank_cd full text search ranking score."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        coalesced = " || ' ' || ".join(
            [f"COALESCE({col}::text, '')" for col in col_refs]
        )
        return f"ts_rank_cd(to_tsvector('english', {coalesced}), plainto_tsquery('english', {ph}))"


class SnowflakeDialect(BaseDialect):
    """Snowflake dialect."""

    name: str = "snowflake"
    # '\\' is itself an escape character inside Snowflake string literals, so use a plain
    # character as the LIKE escape and declare it.
    like_escape_char = "!"
    like_escape_clause = True

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats Snowflake vector similarity expression."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"VECTOR_L2_DISTANCE({col_ref}, {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"VECTOR_INNER_PRODUCT({col_ref}, {self.placeholder})"
        return f"VECTOR_COSINE_SIMILARITY({col_ref}, {self.placeholder})"

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats Snowflake keyword search score expression."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        cases = [
            f"(CASE WHEN CONTAINS(LOWER({col}), LOWER({ph})) THEN 1.0 ELSE 0.0 END)"
            for col in col_refs
        ]
        return f"({' + '.join(cases)})"


class MSSQLDialect(BaseDialect):
    """Microsoft SQL Server dialect using square bracket quoting and FETCH FIRST pagination."""

    name: str = "mssql"
    placeholder: str = "%s"
    requires_order_by_for_pagination: bool = True
    # AVG over an integer column does integer division in T-SQL (AVG(1,2) = 1).
    avg_template = "AVG(CAST({} AS FLOAT))"
    like_escape_char = "\\"
    like_escape_clause = True
    like_special_chars = "%_["

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
    supports_materialized_cte: bool = True
    supports_window_groups_frame: bool = False
    like_escape_char = "\\"
    like_escape_clause = True

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
    like_escape_char = "\\"  # MySQL's default LIKE escape

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
    supports_materialized_cte: bool = True
    supports_window_groups_frame: bool = True
    like_escape_char = "\\"
    like_escape_clause = True

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

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats BigQuery vector distance expression."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"EUCLIDEAN_DISTANCE({col_ref}, {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"DOT_PRODUCT({col_ref}, {self.placeholder})"
        return f"COSINE_DISTANCE({col_ref}, {self.placeholder})"


class ClickHouseDialect(BaseDialect):
    """ClickHouse dialect using backtick quoting and native ILIKE."""

    name: str = "clickhouse"
    placeholder: str = "%s"
    like_escape_char = "\\"  # ClickHouse's default LIKE escape

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

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats ClickHouse vector distance function expression."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"L2Distance({col_ref}, {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"dotProduct({col_ref}, {self.placeholder})"
        return f"cosineDistance({col_ref}, {self.placeholder})"

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats ClickHouse positionCaseInsensitive scoring."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        cases = [
            f"if(positionCaseInsensitive({col}, {ph}) > 0, 1.0, 0.0)"
            for col in col_refs
        ]
        return f"({' + '.join(cases)})"

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table, name FROM system.columns WHERE database = {self.placeholder} AND table = {self.placeholder} AND is_in_primary_key = 1 ORDER BY position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table, name FROM system.columns WHERE database = {self.placeholder} AND is_in_primary_key = 1 ORDER BY table, position;",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class OracleDialect(BaseDialect):
    """Oracle SQL dialect using standard ANSI double-quote escaping and OFFSET-FETCH pagination."""

    name: str = "oracle"
    placeholder: str = "%s"  # OracleConnector rewrites to :1, :2, ... for the driver
    subquery_alias_keyword = ""  # ORA-03048: no AS before a derived-table alias
    like_escape_char = "\\"
    like_escape_clause = True

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
    like_escape_char = "\\"
    like_escape_clause = True

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
    _REGEX_SPECIAL = frozenset(r"\.+*?()|[]{}^$#&-~")

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"

    # Polars' LIKE/ILIKE has NO ESCAPE support (a literal % or _ cannot be expressed), so the
    # contains/starts_with/ends_with operators use its regex match operator instead.
    def substring_param(self, mode: str, value: Any) -> str:
        text = "".join(
            "\\" + ch if ch in self._REGEX_SPECIAL else ch for ch in str(value)
        )
        anchored = (
            ("^" if mode == "starts" else "") + text + ("$" if mode == "ends" else "")
        )
        return "(?i)" + anchored

    def format_substring_match(self, col_ref: str) -> str:
        return f"{col_ref} ~ {self.placeholder}"


class DataFusionDialect(BaseDialect):
    """Apache Arrow DataFusion SQL dialect."""

    name: str = "datafusion"
    placeholder: str = "?"
    like_escape_char = "\\"
    like_escape_clause = True

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
    count_distinct_template = (
        "count_distinct({})"  # COUNT(DISTINCT x) is a syntax error
    )
    like_escape_char = "\\"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # QuestDB has no OFFSET keyword: pagination is `LIMIT lower, upper`
        # (row range [lower, upper)). Integers are inlined after int() coercion.
        lo = max(int(offset), 0)
        return f"LIMIT {lo}, {lo + max(int(limit), 0)}", []


class ElasticsearchDialect(BaseDialect):
    """Elasticsearch / OpenSearch SQL dialect."""

    name: str = "elasticsearch"
    placeholder: str = "?"  # the /_sql endpoint binds positional `?` parameters

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

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

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # pymongosql cannot bind LIMIT/OFFSET (`Invalid LIMIT value '?'`) and then
        # silently returns no rows: inline the int-coerced values.
        clause = f"LIMIT {int(limit)}"
        if int(offset) > 0:
            clause += f" OFFSET {int(offset)}"
        return clause, []


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

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"DESCRIBE `{table_name}`;", [])
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


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


class ExasolDialect(BaseDialect):
    """Exasol high-performance in-memory MP-relational analytics dialect."""

    name: str = "exasol"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

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

    def inspect_foreign_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT CONSTRAINT_TABLE AS src_table, COLUMN_NAME AS src_column, REFERENCED_TABLE AS tgt_table, REFERENCED_COLUMN AS tgt_column FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TABLE = {self.placeholder} AND CONSTRAINT_TYPE = 'FOREIGN KEY';",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT CONSTRAINT_TABLE AS src_table, COLUMN_NAME AS src_column, REFERENCED_TABLE AS tgt_table, REFERENCED_COLUMN AS tgt_column FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TYPE = 'FOREIGN KEY';",
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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("SELECT VALUE c.id FROM c;", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class DorisDialect(BaseDialect):
    """Apache Doris real-time MPP analytical data warehouse dialect."""

    name: str = "doris"
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
        self, schema_name: str = "information_schema"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} AND table_type IN ('BASE TABLE', 'VIEW', 'EXTERNAL TABLE') ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "information_schema", table_name: str | None = None
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
        self, schema_name: str = "information_schema", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} AND (column_key = 'PRI' OR column_key = 'UNI') ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = {self.placeholder} AND (column_key = 'PRI' OR column_key = 'UNI') ORDER BY table_name, ordinal_position;",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "information_schema", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class ImpalaDialect(BaseDialect):
    """Apache Impala low-latency MPP Hadoop/object-store SQL dialect."""

    name: str = "impala"
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
        return (f"SHOW TABLES IN `{schema_name}`;", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"DESCRIBE `{schema_name}`.`{table_name}`;", [])
        return (f"SHOW TABLES IN `{schema_name}`;", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class HiveDialect(BaseDialect):
    """Apache Hive enterprise data lakehouse SQL dialect."""

    name: str = "hive"
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

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return (f"SHOW TABLES IN `{schema_name}`;", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"DESCRIBE `{schema_name}`.`{table_name}`;", [])
        return (f"SHOW TABLES IN `{schema_name}`;", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class KyuubiDialect(BaseDialect):
    """Apache Kyuubi multi-tenant enterprise query gateway dialect."""

    name: str = "kyuubi"
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
        return (f"SHOW TABLES IN `{schema_name}`;", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"DESCRIBE `{schema_name}`.`{table_name}`;", [])
        return (f"SHOW TABLES IN `{schema_name}`;", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class DrillDialect(BaseDialect):
    """Apache Drill distributed schema-free SQL dialect."""

    name: str = "drill"
    placeholder: str = "%s"
    neq_operator = "<>"
    # '!' not '\': sqlglot's Drill tokenizer reads a backslash in a string as an escape,
    # so the AST validator would reject ESCAPE '\'
    like_escape_char = "!"
    like_escape_clause = True

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_ilike(self, col_ref: str) -> str:
        # Drill has no ILIKE operator (only an ILIKE(col, pattern) function without ESCAPE)
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def inspect_tables_query(
        self, schema_name: str = "dfs.default"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = {self.placeholder} ORDER BY TABLE_NAME;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "dfs.default", table_name: str | None = None
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

    def inspect_primary_keys_query(
        self, schema_name: str = "dfs.default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "dfs.default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class YugabyteDBDialect(PostgresDialect):
    """YugabyteDB distributed cloud-native HTAP database dialect."""

    name: str = "yugabyte"


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

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_ilike(self, col_ref: str) -> str:
        return f"toLower({col_ref}) CONTAINS toLower({self.placeholder})"

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

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

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


class ClickHouseNativeDialect(ClickHouseDialect):
    """ClickHouse native binary TCP protocol dialect."""

    name: str = "clickhouse_native"


class FirebirdDialect(BaseDialect):
    """Firebird relational database dialect using double-quote escaping and ROWS pagination."""

    name: str = "firebird"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    like_escape_char = "\\"
    like_escape_clause = True
    # AVG over an INTEGER column is integer division in Firebird
    avg_template = "AVG(CAST({} AS DOUBLE PRECISION))"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # SQL:2008 OFFSET/FETCH (Firebird 3.0+): standard, so the structural validator can
        # parse it (the legacy ``ROWS m TO n`` form is not parseable and was rejected).
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        return (
            "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL ORDER BY RDB$RELATION_NAME;",
            [],
        )

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME), TRIM(f.RDB$FIELD_TYPE), rf.RDB$NULL_FLAG FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME WHERE rf.RDB$SYSTEM_FLAG = 0 AND rf.RDB$RELATION_NAME = {self.placeholder} ORDER BY rf.RDB$FIELD_POSITION;",
                [table_name.upper()],
            )
        return (
            "SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME), TRIM(f.RDB$FIELD_TYPE), rf.RDB$NULL_FLAG FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME WHERE rf.RDB$SYSTEM_FLAG = 0 ORDER BY rf.RDB$RELATION_NAME, rf.RDB$FIELD_POSITION;",
            [],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(iseg.RDB$FIELD_NAME) FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' AND rc.RDB$RELATION_NAME = {self.placeholder} ORDER BY iseg.RDB$FIELD_POSITION;",
                [table_name.upper()],
            )
        return (
            "SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(iseg.RDB$FIELD_NAME) FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' ORDER BY rc.RDB$RELATION_NAME, iseg.RDB$FIELD_POSITION;",
            [],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TRIM(rc.RDB$RELATION_NAME) AS src_table, TRIM(iseg.RDB$FIELD_NAME) AS src_column, TRIM(ref_rc.RDB$RELATION_NAME) AS tgt_table, TRIM(ref_iseg.RDB$FIELD_NAME) AS tgt_column FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$REF_CONSTRAINTS refc ON rc.RDB$CONSTRAINT_NAME = refc.RDB$CONSTRAINT_NAME JOIN RDB$RELATION_CONSTRAINTS ref_rc ON refc.RDB$CONST_NAME_UQ = ref_rc.RDB$CONSTRAINT_NAME JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME JOIN RDB$INDEX_SEGMENTS ref_iseg ON ref_rc.RDB$INDEX_NAME = ref_iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY' AND rc.RDB$RELATION_NAME = {self.placeholder};",
                [table_name.upper()],
            )
        return (
            "SELECT TRIM(rc.RDB$RELATION_NAME) AS src_table, TRIM(iseg.RDB$FIELD_NAME) AS src_column, TRIM(ref_rc.RDB$RELATION_NAME) AS tgt_table, TRIM(ref_iseg.RDB$FIELD_NAME) AS tgt_column FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$REF_CONSTRAINTS refc ON rc.RDB$CONSTRAINT_NAME = refc.RDB$CONSTRAINT_NAME JOIN RDB$RELATION_CONSTRAINTS ref_rc ON refc.RDB$CONST_NAME_UQ = ref_rc.RDB$CONSTRAINT_NAME JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME JOIN RDB$INDEX_SEGMENTS ref_iseg ON ref_rc.RDB$INDEX_NAME = ref_iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY';",
            [],
        )


class MonetDBDialect(BaseDialect):
    """MonetDB columnar analytical database dialect using double-quote escaping and LIMIT/OFFSET."""

    name: str = "monetdb"
    placeholder: str = "%s"  # pymonetdb paramstyle is pyformat
    # MonetDB rejects a backslash ESCAPE; "!" works
    like_escape_char = "!"
    like_escape_clause = True

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(self, schema_name: str = "sys") -> tuple[str, list[Any]]:
        return (
            f"SELECT t.name FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.id WHERE s.name = {self.placeholder} AND t.system = FALSE ORDER BY t.name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "sys", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f'SELECT t.name, c.name, c.type, c."null" FROM sys.columns c JOIN sys.tables t ON c.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE s.name = {self.placeholder} AND t.name = {self.placeholder} ORDER BY c.number;',
                [schema_name, table_name],
            )
        return (
            f'SELECT t.name, c.name, c.type, c."null" FROM sys.columns c JOIN sys.tables t ON c.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE s.name = {self.placeholder} AND t.system = FALSE ORDER BY t.name, c.number;',
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "sys", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.name, kc.name FROM sys.keys k JOIN sys.objects kc ON k.id = kc.id JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE k.type = 0 AND s.name = {self.placeholder} AND t.name = {self.placeholder} ORDER BY kc.nr;",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.name, kc.name FROM sys.keys k JOIN sys.objects kc ON k.id = kc.id JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE k.type = 0 AND s.name = {self.placeholder} ORDER BY t.name, kc.nr;",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "sys", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.name AS src_table, kc.name AS src_column, rt.name AS tgt_table, rkc.name AS tgt_column FROM sys.keys k JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id JOIN sys.objects kc ON k.id = kc.id JOIN sys.keys rk ON k.rkey = rk.id JOIN sys.tables rt ON rk.table_id = rt.id JOIN sys.objects rkc ON rk.id = rkc.id AND kc.nr = rkc.nr WHERE k.type = 2 AND s.name = {self.placeholder} AND t.name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.name AS src_table, kc.name AS src_column, rt.name AS tgt_table, rkc.name AS tgt_column FROM sys.keys k JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id JOIN sys.objects kc ON k.id = kc.id JOIN sys.keys rk ON k.rkey = rk.id JOIN sys.tables rt ON rk.table_id = rt.id JOIN sys.objects rkc ON rk.id = rkc.id AND kc.nr = rkc.nr WHERE s.name = {self.placeholder};",
            [schema_name],
        )


class H2Dialect(BaseDialect):
    """H2 embedded and in-memory Java database dialect using double-quote escaping and LIMIT/OFFSET."""

    name: str = "h2"
    placeholder: str = "?"
    like_escape_char = "\\"  # H2's default LIKE escape
    like_escape_clause = True

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "PUBLIC"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} AND table_type = 'BASE TABLE' ORDER BY table_name;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name.upper()],
        )


class DerbyDialect(BaseDialect):
    """Apache Derby relational database dialect using double-quote escaping and OFFSET/FETCH pagination."""

    name: str = "derby"
    placeholder: str = "?"
    like_escape_char = "\\"  # Derby has no default LIKE escape: declare it
    like_escape_clause = True

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(self, schema_name: str = "APP") -> tuple[str, list[Any]]:
        return (
            f"SELECT t.TABLENAME FROM SYS.SYSTABLES t JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE s.SCHEMANAME = {self.placeholder} AND t.TABLETYPE = 'T' ORDER BY t.TABLENAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "APP", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.TABLENAME, c.COLUMNNAME, c.COLUMNDATATYPE, c.AUTOINCREMENTVALUE FROM SYS.SYSCOLUMNS c JOIN SYS.SYSTABLES t ON c.REFERENCEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE s.SCHEMANAME = {self.placeholder} AND t.TABLENAME = {self.placeholder} ORDER BY c.COLUMNNUMBER;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT t.TABLENAME, c.COLUMNNAME, c.COLUMNDATATYPE, c.AUTOINCREMENTVALUE FROM SYS.SYSCOLUMNS c JOIN SYS.SYSTABLES t ON c.REFERENCEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE s.SCHEMANAME = {self.placeholder} ORDER BY t.TABLENAME, c.COLUMNNUMBER;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "APP", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.TABLENAME, c.CONSTRAINTNAME FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE c.TYPE = 'P' AND s.SCHEMANAME = {self.placeholder} AND t.TABLENAME = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT t.TABLENAME, c.CONSTRAINTNAME FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE c.TYPE = 'P' AND s.SCHEMANAME = {self.placeholder};",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "APP", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.TABLENAME AS src_table, c.CONSTRAINTNAME AS src_column, rt.TABLENAME AS tgt_table, rc.CONSTRAINTNAME AS tgt_column FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID JOIN SYS.SYSKEYS k ON c.CONSTRAINTID = k.CONSTRAINTID JOIN SYS.SYSCONSTRAINTS rc ON k.CONGLOMERATEID = rc.CONSTRAINTID JOIN SYS.SYSTABLES rt ON rc.TABLEID = rt.TABLEID WHERE c.TYPE = 'F' AND s.SCHEMANAME = {self.placeholder} AND t.TABLENAME = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT t.TABLENAME AS src_table, c.CONSTRAINTNAME AS src_column, rt.TABLENAME AS tgt_table, rc.CONSTRAINTNAME AS tgt_column FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID JOIN SYS.SYSKEYS k ON c.CONSTRAINTID = k.CONSTRAINTID JOIN SYS.SYSCONSTRAINTS rc ON k.CONGLOMERATEID = rc.CONSTRAINTID JOIN SYS.SYSTABLES rt ON rc.TABLEID = rt.TABLEID WHERE c.TYPE = 'F' AND s.SCHEMANAME = {self.placeholder};",
            [schema_name.upper()],
        )


class SybaseDialect(BaseDialect):
    """Sybase / SAP ASE database dialect using square bracket quoting and T-SQL pagination."""

    name: str = "sybase"
    placeholder: str = "?"

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

    def inspect_tables_query(self, schema_name: str = "dbo") -> tuple[str, list[Any]]:
        return (
            "SELECT name FROM sysobjects WHERE type = 'U' ORDER BY name;",
            [],
        )

    def inspect_columns_query(
        self, schema_name: str = "dbo", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT o.name, c.name, t.name, c.status FROM syscolumns c JOIN sysobjects o ON c.id = o.id JOIN systypes t ON c.usertype = t.usertype WHERE o.type = 'U' AND o.name = {self.placeholder} ORDER BY c.colid;",
                [table_name],
            )
        return (
            "SELECT o.name, c.name, t.name, c.status FROM syscolumns c JOIN sysobjects o ON c.id = o.id JOIN systypes t ON c.usertype = t.usertype WHERE o.type = 'U' ORDER BY o.name, c.colid;",
            [],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "dbo", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT o.name, c.name FROM sysconstraints con JOIN sysobjects o ON con.tableid = o.id JOIN syscolumns c ON con.tableid = c.id WHERE con.status = 1 AND o.type = 'U' AND o.name = {self.placeholder};",
                [table_name],
            )
        return (
            "SELECT o.name, c.name FROM sysconstraints con JOIN sysobjects o ON con.tableid = o.id JOIN syscolumns c ON con.tableid = c.id WHERE con.status = 1 AND o.type = 'U';",
            [],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "dbo", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT so.name AS src_table, sc.name AS src_column, ro.name AS tgt_table, rc.name AS tgt_column FROM sysreferences r JOIN sysobjects so ON r.tableid = so.id JOIN sysobjects ro ON r.reftabid = ro.id JOIN syscolumns sc ON r.tableid = sc.id JOIN syscolumns rc ON r.reftabid = rc.id WHERE so.name = {self.placeholder};",
                [table_name],
            )
        return (
            "SELECT so.name AS src_table, sc.name AS src_column, ro.name AS tgt_table, rc.name AS tgt_column FROM sysreferences r JOIN sysobjects so ON r.tableid = so.id JOIN sysobjects ro ON r.reftabid = ro.id JOIN syscolumns sc ON r.tableid = sc.id JOIN syscolumns rc ON r.reftabid = rc.id;",
            [],
        )


class InformixDialect(BaseDialect):
    """IBM Informix Dynamic Server dialect using double-quote escaping and SKIP/FIRST pagination."""

    name: str = "informix"
    placeholder: str = "%s"
    pagination_placement: str = "prefix"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"SKIP {self.placeholder} FIRST {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "informix"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT tabname FROM systables WHERE tabtype = 'T' AND owner = {self.placeholder} ORDER BY tabname;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "informix", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.tabname, c.colname, c.coltype, c.collength FROM syscolumns c JOIN systables t ON c.tabid = t.tabid WHERE t.tabtype = 'T' AND t.owner = {self.placeholder} AND t.tabname = {self.placeholder} ORDER BY c.colno;",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.tabname, c.colname, c.coltype, c.collength FROM syscolumns c JOIN systables t ON c.tabid = t.tabid WHERE t.tabtype = 'T' AND t.owner = {self.placeholder} ORDER BY t.tabname, c.colno;",
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "informix", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.tabname, c.constrname FROM sysconstraints c JOIN systables t ON c.tabid = t.tabid WHERE c.constrtype = 'P' AND t.owner = {self.placeholder} AND t.tabname = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.tabname, c.constrname FROM sysconstraints c JOIN systables t ON c.tabid = t.tabid WHERE c.constrtype = 'P' AND t.owner = {self.placeholder};",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "informix", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.tabname AS src_table, c.constrname AS src_column, pt.tabname AS tgt_table, pc.constrname AS tgt_column FROM sysreferences r JOIN sysconstraints c ON r.constrid = c.constrid JOIN systables t ON c.tabid = t.tabid JOIN sysconstraints pc ON r.primaryid = pc.constrid JOIN systables pt ON pc.tabid = pt.tabid WHERE t.owner = {self.placeholder} AND t.tabname = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.tabname AS src_table, c.constrname AS src_column, pt.tabname AS tgt_table, pc.constrname AS tgt_column FROM sysreferences r JOIN sysconstraints c ON r.constrid = c.constrid JOIN systables t ON c.tabid = t.tabid JOIN sysconstraints pc ON r.primaryid = pc.constrid JOIN systables pt ON pc.tabid = pt.tabid WHERE t.owner = {self.placeholder};",
            [schema_name],
        )


class KustoDialect(BaseDialect):
    """Azure Data Explorer / Kusto / KQL dialect."""

    name: str = "kusto"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} =~ {self.placeholder}"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return ".show tables", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f".show table {table_name} schema as json", []
        return ".show database schema as json", []

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class PrometheusDialect(BaseDialect):
    """Prometheus PromQL time-series metrics dialect."""

    name: str = "prometheus"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f'{col_ref}=~"(?i){self.placeholder}"'

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "/api/v1/label/__name__/values", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "/api/v1/labels", []

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class VictoriaMetricsDialect(BaseDialect):
    """VictoriaMetrics MetricsQL time-series observability dialect."""

    name: str = "victoriametrics"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f'{col_ref}=~"(?i){self.placeholder}"'

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "/api/v1/label/__name__/values", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "/api/v1/labels", []

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class TimestreamDialect(BaseDialect):
    """Amazon Web Services (AWS) Timestream SQL time-series dialect."""

    name: str = "timestream"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return f'SHOW TABLES FROM "{schema_name}"', []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f'DESCRIBE "{schema_name}"."{table_name}"', []
        return f'SHOW TABLES FROM "{schema_name}"', []

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class MemgraphDialect(BaseDialect):
    """Memgraph in-memory OpenCypher graph database dialect."""

    name: str = "memgraph"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_ilike(self, col_ref: str) -> str:
        return f"toLower({col_ref}) CONTAINS toLower({self.placeholder})"

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

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_ilike(self, col_ref: str) -> str:
        return f"toLower({col_ref}) CONTAINS toLower({self.placeholder})"

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


class KsqlDBDialect(BaseDialect):
    """ksqlDB event streaming database pull query SQL dialect."""

    name: str = "ksqldb"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_ilike(self, col_ref: str) -> str:
        return f"LCASE({col_ref}) LIKE LCASE({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        return "SHOW TABLES;", []

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"DESCRIBE {table_name};", []
        return "SHOW STREAMS;", []

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class FlinkDialect(BaseDialect):
    """Apache Flink SQL streaming table dialect."""

    name: str = "flink"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "default_database"
    ) -> tuple[str, list[Any]]:
        return "SHOW TABLES;", []

    def inspect_columns_query(
        self, schema_name: str = "default_database", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"DESCRIBE `{table_name}`;", []
        return "SHOW TABLES;", []

    def inspect_primary_keys_query(
        self, schema_name: str = "default_database", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default_database", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class PulsarDialect(BaseDialect):
    """Apache Pulsar SQL interactive topic query dialect."""

    name: str = "pulsar"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "pulsar.public/default"
    ) -> tuple[str, list[Any]]:
        return f"SHOW TABLES FROM {schema_name};", []

    def inspect_columns_query(
        self, schema_name: str = "pulsar.public/default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f'DESCRIBE {schema_name}."{table_name}";', []
        return f"SHOW TABLES FROM {schema_name};", []

    def inspect_primary_keys_query(
        self, schema_name: str = "pulsar.public/default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "pulsar.public/default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class QdrantDialect(BaseDialect):
    """Qdrant vector search engine filter dialect."""

    name: str = "qdrant"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class PineconeDialect(BaseDialect):
    """Pinecone managed vector database dialect."""

    name: str = "pinecone"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class WeaviateDialect(BaseDialect):
    """Weaviate modular vector database and knowledge graph dialect."""

    name: str = "weaviate"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class MilvusDialect(BaseDialect):
    """Milvus distributed cloud-native vector database dialect."""

    name: str = "milvus"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class ChromaDialect(BaseDialect):
    """ChromaDB embedded and server AI vector database dialect."""

    name: str = "chroma"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class LanceDBDialect(BaseDialect):
    """LanceDB Apache Arrow-backed columnar vector database dialect."""

    name: str = "lancedb"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER(?)"

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class RedisSearchDialect(BaseDialect):
    """Redis RediSearch secondary index query dialect."""

    name: str = "redis"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"@{part}" for part in parts)

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref}:{self.placeholder}%"

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class FirestoreDialect(BaseDialect):
    """Google Cloud Firestore document database dialect."""

    name: str = "firestore"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


class BigtableDialect(BaseDialect):
    """Google Cloud Bigtable wide-column database dialect."""

    name: str = "bigtable"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

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

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []


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
    "opensearch": OpenSearchDialect(),
    "opensearch_sql": OpenSearchDialect(),
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
    "doris": DorisDialect(),
    "apache_doris": DorisDialect(),
    "pydoris": DorisDialect(),
    "impala": ImpalaDialect(),
    "apache_impala": ImpalaDialect(),
    "impyla": ImpalaDialect(),
    "hive": HiveDialect(),
    "apache_hive": HiveDialect(),
    "pyhive": HiveDialect(),
    "kyuubi": KyuubiDialect(),
    "apache_kyuubi": KyuubiDialect(),
    "drill": DrillDialect(),
    "apache_drill": DrillDialect(),
    "pydrill": DrillDialect(),
    "yugabyte": YugabyteDBDialect(),
    "yugabytedb": YugabyteDBDialect(),
    "neo4j": Neo4jDialect(),
    "cypher": Neo4jDialect(),
    "neo4j_sql": Neo4jDialect(),
    "kdb": KdbDialect(),
    "kdb+": KdbDialect(),
    "pykx": KdbDialect(),
    "q": KdbDialect(),
    "clickhouse_native": ClickHouseNativeDialect(),
    "ch_native": ClickHouseNativeDialect(),
    "clickhouse_tcp": ClickHouseNativeDialect(),
    "firebird": FirebirdDialect(),
    "firebirdsql": FirebirdDialect(),
    "monetdb": MonetDBDialect(),
    "monet": MonetDBDialect(),
    "h2": H2Dialect(),
    "h2db": H2Dialect(),
    "derby": DerbyDialect(),
    "apache_derby": DerbyDialect(),
    "sybase": SybaseDialect(),
    "sap_ase": SybaseDialect(),
    "ase": SybaseDialect(),
    "informix": InformixDialect(),
    "ibm_informix": InformixDialect(),
    "kusto": KustoDialect(),
    "adx": KustoDialect(),
    "azure_data_explorer": KustoDialect(),
    "kql": KustoDialect(),
    "prometheus": PrometheusDialect(),
    "prom": PrometheusDialect(),
    "promql": PrometheusDialect(),
    "victoriametrics": VictoriaMetricsDialect(),
    "vm": VictoriaMetricsDialect(),
    "metricsql": VictoriaMetricsDialect(),
    "timestream": TimestreamDialect(),
    "aws_timestream": TimestreamDialect(),
    "memgraph": MemgraphDialect(),
    "memgraph_db": MemgraphDialect(),
    "neptune": NeptuneDialect(),
    "amazon_neptune": NeptuneDialect(),
    "aws_neptune": NeptuneDialect(),
    "ksqldb": KsqlDBDialect(),
    "ksql": KsqlDBDialect(),
    "flink": FlinkDialect(),
    "flink_sql": FlinkDialect(),
    "apache_flink": FlinkDialect(),
    "pulsar": PulsarDialect(),
    "pulsar_sql": PulsarDialect(),
    "apache_pulsar": PulsarDialect(),
    "qdrant": QdrantDialect(),
    "qdrant_db": QdrantDialect(),
    "qdrant_vector": QdrantDialect(),
    "pinecone": PineconeDialect(),
    "pinecone_db": PineconeDialect(),
    "pinecone_vector": PineconeDialect(),
    "weaviate": WeaviateDialect(),
    "weaviate_db": WeaviateDialect(),
    "weaviate_vector": WeaviateDialect(),
    "milvus": MilvusDialect(),
    "pymilvus": MilvusDialect(),
    "zilliz": MilvusDialect(),
    "milvus_vector": MilvusDialect(),
    "chroma": ChromaDialect(),
    "chromadb": ChromaDialect(),
    "lancedb": LanceDBDialect(),
    "lance": LanceDBDialect(),
    "redis": RedisSearchDialect(),
    "redisearch": RedisSearchDialect(),
    "redis_search": RedisSearchDialect(),
    "firestore": FirestoreDialect(),
    "google_firestore": FirestoreDialect(),
    "gcp_firestore": FirestoreDialect(),
    "bigtable": BigtableDialect(),
    "google_bigtable": BigtableDialect(),
    "gcp_bigtable": BigtableDialect(),
}


def get_dialect(name: str | None = None) -> BaseDialect:
    """Returns the dialect instance for the specified name (defaults to configured default dialect or postgres)."""
    if name is None:
        try:
            from query_builder.config import get_query_builder_config

            default_name = get_query_builder_config().default_dialect
            return DIALECTS.get(default_name.lower().strip(), DIALECTS["postgres"])
        except (ImportError, AttributeError, KeyError):
            return DIALECTS["postgres"]
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
