"""
Pluggable Connectors Package for Query Builder Engine.
======================================================
Provides pre-configured database connectors, introspection utilities,
and dynamic registry discovery.
"""

from query_builder.connectors.athena import AthenaConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    ConnectorError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.bigquery import BigQueryConnector
from query_builder.connectors.clickhouse import ClickHouseConnector
from query_builder.connectors.cockroachdb import CockroachConnector
from query_builder.connectors.databricks import DatabricksConnector
from query_builder.connectors.datafusion import DataFusionConnector
from query_builder.connectors.duckdb import DuckDBConnector
from query_builder.connectors.dynamodb import DynamoDBConnector
from query_builder.connectors.elasticsearch import ElasticsearchConnector
from query_builder.connectors.generic import GenericDBAPIConnector
from query_builder.connectors.introspection import (
    introspect_clickhouse,
    introspect_duckdb,
    introspect_information_schema,
    introspect_oracle,
    introspect_sqlite,
    introspect_via_sqlalchemy,
)
from query_builder.connectors.mssql import MSSQLConnector
from query_builder.connectors.mysql import MySQLConnector
from query_builder.connectors.oracle import OracleConnector
from query_builder.connectors.polars import PolarsConnector
from query_builder.connectors.postgres import PostgresConnector
from query_builder.connectors.questdb import QuestDBConnector
from query_builder.connectors.redshift import RedshiftConnector
from query_builder.connectors.registry import (
    ConnectorRegistry,
    get_connector,
    list_connectors,
    register_connector,
)
from query_builder.connectors.snowflake import SnowflakeConnector
from query_builder.connectors.spanner import SpannerConnector
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.connectors.timescaledb import TimescaleConnector
from query_builder.connectors.trino import TrinoConnector

# Auto-register all built-in connectors into the central registry
ConnectorRegistry.register("sqlite", SQLiteConnector)
ConnectorRegistry.register("duckdb", DuckDBConnector)
ConnectorRegistry.register("postgres", PostgresConnector, aliases=["postgresql"])
ConnectorRegistry.register("mysql", MySQLConnector, aliases=["mariadb"])
ConnectorRegistry.register("mssql", MSSQLConnector, aliases=["sqlserver"])
ConnectorRegistry.register("snowflake", SnowflakeConnector)
ConnectorRegistry.register("bigquery", BigQueryConnector)
ConnectorRegistry.register("clickhouse", ClickHouseConnector)
ConnectorRegistry.register("oracle", OracleConnector)
ConnectorRegistry.register("redshift", RedshiftConnector)
ConnectorRegistry.register("trino", TrinoConnector, aliases=["presto"])
ConnectorRegistry.register("databricks", DatabricksConnector, aliases=["spark"])
ConnectorRegistry.register("athena", AthenaConnector)
ConnectorRegistry.register("polars", PolarsConnector)
ConnectorRegistry.register("datafusion", DataFusionConnector)
ConnectorRegistry.register("timescaledb", TimescaleConnector, aliases=["timescale"])
ConnectorRegistry.register("cockroachdb", CockroachConnector, aliases=["cockroach"])
ConnectorRegistry.register("spanner", SpannerConnector)
ConnectorRegistry.register("questdb", QuestDBConnector)
ConnectorRegistry.register(
    "elasticsearch", ElasticsearchConnector, aliases=["opensearch"]
)
ConnectorRegistry.register("dynamodb", DynamoDBConnector, aliases=["partiql"])
ConnectorRegistry.register("generic", GenericDBAPIConnector, aliases=["dbapi"])

__all__ = [
    "AthenaConnector",
    "BaseConnector",
    "BigQueryConnector",
    "ClickHouseConnector",
    "CockroachConnector",
    "ConnectionFailedError",
    "ConnectorError",
    "ConnectorRegistry",
    "DataFusionConnector",
    "DatabricksConnector",
    "DriverNotInstalledError",
    "DuckDBConnector",
    "DynamoDBConnector",
    "ElasticsearchConnector",
    "GenericDBAPIConnector",
    "IntrospectionError",
    "MSSQLConnector",
    "MySQLConnector",
    "OracleConnector",
    "PolarsConnector",
    "PostgresConnector",
    "QuestDBConnector",
    "RedshiftConnector",
    "SQLiteConnector",
    "SnowflakeConnector",
    "SpannerConnector",
    "TimescaleConnector",
    "TrinoConnector",
    "get_connector",
    "introspect_clickhouse",
    "introspect_duckdb",
    "introspect_information_schema",
    "introspect_oracle",
    "introspect_sqlite",
    "introspect_via_sqlalchemy",
    "list_connectors",
    "register_connector",
]
