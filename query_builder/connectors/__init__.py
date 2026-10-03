"""
Pluggable Connectors Package for Query Builder Engine.
======================================================
Provides pre-configured database connectors, introspection utilities,
and dynamic registry discovery.
"""

from query_builder.connectors.alloydb import AlloyDBConnector
from query_builder.connectors.async_base import AsyncBaseConnector
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
from query_builder.connectors.couchbase import (
    CouchbaseConnector,
    N1QLConnector,
)
from query_builder.connectors.cratedb import (
    AsyncCrateConnector,
    AsyncCrateDBConnector,
    CrateConnector,
    CrateDBConnector,
)
from query_builder.connectors.d1 import (
    CloudflareD1Connector,
    D1Connector,
)
from query_builder.connectors.databricks import DatabricksConnector
from query_builder.connectors.datafusion import DataFusionConnector
from query_builder.connectors.dremio import DremioConnector
from query_builder.connectors.druid import DruidConnector
from query_builder.connectors.duckdb import DuckDBConnector
from query_builder.connectors.dynamodb import DynamoDBConnector
from query_builder.connectors.elasticsearch import ElasticsearchConnector
from query_builder.connectors.firebolt import FireboltConnector
from query_builder.connectors.generic import GenericDBAPIConnector
from query_builder.connectors.influxdb import (
    InfluxDBConnector,
    IOxConnector,
)
from query_builder.connectors.introspection import (
    introspect_clickhouse,
    introspect_cratedb,
    introspect_druid,
    introspect_duckdb,
    introspect_information_schema,
    introspect_oracle,
    introspect_saphana,
    introspect_scylladb,
    introspect_sqlite,
    introspect_via_sqlalchemy,
)
from query_builder.connectors.materialize import (
    AsyncMaterializeConnector,
    MaterializeConnector,
)
from query_builder.connectors.mongodb import (
    MongoDBAtlasSQLConnector,
    MongoDBConnector,
)
from query_builder.connectors.mssql import MSSQLConnector
from query_builder.connectors.mysql import MySQLConnector
from query_builder.connectors.neon import NeonConnector
from query_builder.connectors.oceanbase import OceanBaseConnector
from query_builder.connectors.oracle import OracleConnector
from query_builder.connectors.pinot import PinotConnector
from query_builder.connectors.polars import PolarsConnector
from query_builder.connectors.postgres import PostgresConnector
from query_builder.connectors.prestodb import (
    AsyncPrestoConnector,
    AsyncPrestoDBConnector,
    PrestoConnector,
    PrestoDBConnector,
)
from query_builder.connectors.questdb import QuestDBConnector
from query_builder.connectors.redshift import RedshiftConnector
from query_builder.connectors.registry import (
    ConnectorRegistry,
    get_connector,
    list_connectors,
    register_connector,
)
from query_builder.connectors.risingwave import (
    AsyncRisingWaveConnector,
    RisingWaveConnector,
)
from query_builder.connectors.saphana import (
    HANAConnector,
    SAPHANAConnector,
)
from query_builder.connectors.scylladb import (
    CassandraConnector,
    ScyllaDBConnector,
)
from query_builder.connectors.singlestore import (
    MemSQLConnector,
    SingleStoreConnector,
)
from query_builder.connectors.snowflake import SnowflakeConnector
from query_builder.connectors.spanner import SpannerConnector
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.connectors.starrocks import (
    AsyncStarRocksConnector,
    StarRocksConnector,
)
from query_builder.connectors.supabase import SupabaseConnector
from query_builder.connectors.teradata import TeradataConnector
from query_builder.connectors.tidb import TiDBConnector
from query_builder.connectors.timescaledb import TimescaleConnector
from query_builder.connectors.trino import TrinoConnector
from query_builder.connectors.vertica import VerticaConnector

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
ConnectorRegistry.register("dremio", DremioConnector)
ConnectorRegistry.register("firebolt", FireboltConnector)
ConnectorRegistry.register("tidb", TiDBConnector)
ConnectorRegistry.register("singlestore", SingleStoreConnector, aliases=["memsql"])
ConnectorRegistry.register("teradata", TeradataConnector)
ConnectorRegistry.register("couchbase", CouchbaseConnector, aliases=["n1ql"])
ConnectorRegistry.register("d1", D1Connector, aliases=["cloudflare_d1"])
ConnectorRegistry.register(
    "mongodb", MongoDBAtlasSQLConnector, aliases=["mongo", "atlas_sql"]
)
ConnectorRegistry.register("neon", NeonConnector)
ConnectorRegistry.register("supabase", SupabaseConnector)

# Expanded analytical, streaming, time-series, and distributed SQL connectors
ConnectorRegistry.register("prestodb", PrestoDBConnector, aliases=["presto"])
ConnectorRegistry.register(
    "async_prestodb", AsyncPrestoDBConnector, aliases=["async_presto"]
)
ConnectorRegistry.register("druid", DruidConnector, aliases=["apache_druid"])
ConnectorRegistry.register("pinot", PinotConnector, aliases=["apache_pinot"])
ConnectorRegistry.register("starrocks", StarRocksConnector)
ConnectorRegistry.register("async_starrocks", AsyncStarRocksConnector)
ConnectorRegistry.register("materialize", MaterializeConnector, aliases=["mz"])
ConnectorRegistry.register(
    "async_materialize", AsyncMaterializeConnector, aliases=["async_mz"]
)
ConnectorRegistry.register("risingwave", RisingWaveConnector, aliases=["rw"])
ConnectorRegistry.register(
    "async_risingwave", AsyncRisingWaveConnector, aliases=["async_rw"]
)
ConnectorRegistry.register("cratedb", CrateDBConnector, aliases=["crate"])
ConnectorRegistry.register(
    "async_cratedb", AsyncCrateDBConnector, aliases=["async_crate"]
)
ConnectorRegistry.register("influxdb", InfluxDBConnector, aliases=["iox", "influx"])
ConnectorRegistry.register("alloydb", AlloyDBConnector)
ConnectorRegistry.register("vertica", VerticaConnector)
ConnectorRegistry.register("saphana", SAPHANAConnector, aliases=["hana", "sap_hana"])
ConnectorRegistry.register("oceanbase", OceanBaseConnector)
ConnectorRegistry.register(
    "scylladb", ScyllaDBConnector, aliases=["scylla", "cassandra", "cql"]
)

__all__ = [
    "AlloyDBConnector",
    "AsyncBaseConnector",
    "AsyncCrateConnector",
    "AsyncCrateDBConnector",
    "AsyncMaterializeConnector",
    "AsyncPrestoConnector",
    "AsyncPrestoDBConnector",
    "AsyncRisingWaveConnector",
    "AsyncStarRocksConnector",
    "AthenaConnector",
    "BaseConnector",
    "BigQueryConnector",
    "CassandraConnector",
    "ClickHouseConnector",
    "CloudflareD1Connector",
    "CockroachConnector",
    "ConnectionFailedError",
    "ConnectorError",
    "ConnectorRegistry",
    "CouchbaseConnector",
    "CrateConnector",
    "CrateDBConnector",
    "D1Connector",
    "DataFusionConnector",
    "DatabricksConnector",
    "DremioConnector",
    "DriverNotInstalledError",
    "DruidConnector",
    "DuckDBConnector",
    "DynamoDBConnector",
    "ElasticsearchConnector",
    "FireboltConnector",
    "GenericDBAPIConnector",
    "HANAConnector",
    "IOxConnector",
    "InfluxDBConnector",
    "IntrospectionError",
    "MSSQLConnector",
    "MaterializeConnector",
    "MemSQLConnector",
    "MongoDBAtlasSQLConnector",
    "MongoDBConnector",
    "MySQLConnector",
    "N1QLConnector",
    "NeonConnector",
    "OceanBaseConnector",
    "OracleConnector",
    "PinotConnector",
    "PolarsConnector",
    "PostgresConnector",
    "PrestoConnector",
    "PrestoDBConnector",
    "QuestDBConnector",
    "RedshiftConnector",
    "RisingWaveConnector",
    "SAPHANAConnector",
    "SQLiteConnector",
    "ScyllaDBConnector",
    "SingleStoreConnector",
    "SnowflakeConnector",
    "SpannerConnector",
    "StarRocksConnector",
    "SupabaseConnector",
    "TeradataConnector",
    "TiDBConnector",
    "TimescaleConnector",
    "TrinoConnector",
    "VerticaConnector",
    "get_connector",
    "introspect_clickhouse",
    "introspect_cratedb",
    "introspect_druid",
    "introspect_duckdb",
    "introspect_information_schema",
    "introspect_oracle",
    "introspect_saphana",
    "introspect_scylladb",
    "introspect_sqlite",
    "introspect_via_sqlalchemy",
    "list_connectors",
    "register_connector",
]
