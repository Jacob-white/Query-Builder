"""Time-series, observability and stream-processing dialects."""

from __future__ import annotations

from typing import Any

from query_builder.dialects.base import (
    BaseDialect,
    _validate_alias,
    _validate_identifier,
)


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


class InfluxDBDialect(BaseDialect):
    """InfluxDB v3 / IOx SQL time-series engine dialect."""

    name: str = "influxdb"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


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
