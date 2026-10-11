"""Analytical warehouses, lakehouses, OLAP stores and distributed SQL engines."""

from __future__ import annotations

from typing import Any

from query_builder.dialects.base import (
    BaseDialect,
    _validate_alias,
    _validate_identifier,
)


class BigQueryDialect(BaseDialect):
    """Google BigQuery standard SQL dialect using backtick quoting."""

    name: str = "bigquery"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

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


class TrinoDialect(BaseDialect):
    """Trino SQL dialect using double-quote escaping and OFFSET/LIMIT pagination."""

    name: str = "trino"
    placeholder: str = "?"
    like_escape_char = "\\"
    like_escape_clause = True
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

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
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"


class AthenaDialect(BaseDialect):
    """AWS Athena dialect based on Presto/Trino standard SQL."""

    name: str = "athena"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"


class PolarsDialect(BaseDialect):
    """Polars SQLContext dialect with native ILIKE and question mark placeholders."""

    name: str = "polars"
    placeholder: str = "?"
    _REGEX_SPECIAL = frozenset(r"\.+*?()|[]{}^$#&-~")

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
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"


class DremioDialect(BaseDialect):
    """Dremio SQL Lakehouse platform dialect using Arrow Flight / DB-API."""

    name: str = "dremio"
    placeholder: str = "?"


class FireboltDialect(BaseDialect):
    """Firebolt ultra-low latency cloud data warehouse dialect."""

    name: str = "firebolt"
    placeholder: str = "?"


class DruidDialect(BaseDialect):
    """Apache Druid real-time analytical database dialect."""

    name: str = "druid"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

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
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"


class StarRocksDialect(BaseDialect):
    """StarRocks distributed MPP analytical database dialect."""

    name: str = "starrocks"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"  # no ILIKE operator
    like_escape_char = "\\"  # MySQL-compatible default LIKE escape

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"


class SparkSQLDialect(BaseDialect):
    """Apache Spark SQL dialect using backticks and Hive metastore / Delta Lake conventions."""

    name: str = "sparksql"
    placeholder: str = "%s"
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

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


class ChDBDialect(ClickHouseDialect):
    """chDB in-process ClickHouse SQL OLAP dialect."""

    name: str = "chdb"


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
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

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


class HiveDialect(BaseDialect):
    """Apache Hive enterprise data lakehouse SQL dialect."""

    name: str = "hive"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

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


class KyuubiDialect(BaseDialect):
    """Apache Kyuubi multi-tenant enterprise query gateway dialect."""

    name: str = "kyuubi"
    placeholder: str = "%s"
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

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


class DrillDialect(BaseDialect):
    """Apache Drill distributed schema-free SQL dialect."""

    name: str = "drill"
    placeholder: str = "%s"
    neq_operator = "<>"
    # '!' not '\': sqlglot's Drill tokenizer reads a backslash in a string as an escape,
    # so the AST validator would reject ESCAPE '\'
    like_escape_char = "!"
    like_escape_clause = True
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

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


class ClickHouseNativeDialect(ClickHouseDialect):
    """ClickHouse native binary TCP protocol dialect."""

    name: str = "clickhouse_native"
