"""
Pluggable Connectors Package for Query Builder Engine.
======================================================
Provides pre-configured database connectors, introspection utilities,
and dynamic registry discovery.
"""

from query_builder.connectors.alloydb import AlloyDBConnector
from query_builder.connectors.arangodb import (
    ArangoDBConnector,
    AsyncArangoDBConnector,
)
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
from query_builder.connectors.cassandra import (
    ApacheCassandraConnector,
    AsyncApacheCassandraConnector,
    AsyncCassandraConnector,
)
from query_builder.connectors.chdb import (
    AsyncChDBConnector,
    ChDBConnector,
)
from query_builder.connectors.clickhouse import ClickHouseConnector
from query_builder.connectors.cockroachdb import CockroachConnector
from query_builder.connectors.cosmosdb import (
    AsyncAzureCosmosDBConnector,
    AsyncCosmosDBConnector,
    AzureCosmosDBConnector,
    CosmosDBConnector,
)
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
from query_builder.connectors.db2 import (
    AsyncDB2Connector,
    AsyncIBMDB2Connector,
    DB2Connector,
    IBMDB2Connector,
)
from query_builder.connectors.dremio import DremioConnector
from query_builder.connectors.druid import DruidConnector
from query_builder.connectors.duckdb import DuckDBConnector
from query_builder.connectors.dynamodb import DynamoDBConnector
from query_builder.connectors.elasticsearch import ElasticsearchConnector
from query_builder.connectors.exasol import (
    AsyncExasolConnector,
    ExasolConnector,
)
from query_builder.connectors.firebolt import FireboltConnector
from query_builder.connectors.generic import GenericDBAPIConnector
from query_builder.connectors.greptimedb import (
    AsyncGreptimeDBConnector,
    GreptimeDBConnector,
)
from query_builder.connectors.influxdb import (
    InfluxDBConnector,
    IOxConnector,
)
from query_builder.connectors.introspection import (
    introspect_arangodb,
    introspect_cassandra,
    introspect_chdb,
    introspect_clickhouse,
    introspect_cosmosdb,
    introspect_cratedb,
    introspect_db2,
    introspect_druid,
    introspect_duckdb,
    introspect_exasol,
    introspect_greptimedb,
    introspect_information_schema,
    introspect_oracle,
    introspect_saphana,
    introspect_scylladb,
    introspect_sparksql,
    introspect_sqlite,
    introspect_surrealdb,
    introspect_tdengine,
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
from query_builder.connectors.spark import (
    AsyncSparkConnector,
    AsyncSparkSQLConnector,
    SparkConnector,
    SparkSQLConnector,
)
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.connectors.starrocks import (
    AsyncStarRocksConnector,
    StarRocksConnector,
)
from query_builder.connectors.supabase import SupabaseConnector
from query_builder.connectors.surrealdb import (
    AsyncSurrealDBConnector,
    SurrealDBConnector,
)
from query_builder.connectors.tdengine import (
    AsyncTDengineConnector,
    TDengineConnector,
)
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

# Lakehouse, in-process, time-series, multi-model, and enterprise engines
ConnectorRegistry.register(
    "sparksql", SparkSQLConnector, aliases=["spark_sql", "pyspark"]
)
ConnectorRegistry.register(
    "async_sparksql",
    AsyncSparkSQLConnector,
    aliases=["async_spark_sql", "async_pyspark"],
)
ConnectorRegistry.register("chdb", ChDBConnector)
ConnectorRegistry.register("async_chdb", AsyncChDBConnector)
ConnectorRegistry.register("greptimedb", GreptimeDBConnector, aliases=["greptime"])
ConnectorRegistry.register(
    "async_greptimedb", AsyncGreptimeDBConnector, aliases=["async_greptime"]
)
ConnectorRegistry.register("tdengine", TDengineConnector, aliases=["taos"])
ConnectorRegistry.register(
    "async_tdengine", AsyncTDengineConnector, aliases=["async_taos"]
)
ConnectorRegistry.register("surrealdb", SurrealDBConnector, aliases=["surreal"])
ConnectorRegistry.register(
    "async_surrealdb", AsyncSurrealDBConnector, aliases=["async_surreal"]
)
ConnectorRegistry.register("arangodb", ArangoDBConnector, aliases=["arango", "aql"])
ConnectorRegistry.register(
    "async_arangodb", AsyncArangoDBConnector, aliases=["async_arango", "async_aql"]
)
ConnectorRegistry.register(
    "apache_cassandra", ApacheCassandraConnector, aliases=["apache-cassandra"]
)
ConnectorRegistry.register(
    "async_apache_cassandra",
    AsyncApacheCassandraConnector,
    aliases=["async_apache-cassandra"],
)
ConnectorRegistry.register("exasol", ExasolConnector)
ConnectorRegistry.register("async_exasol", AsyncExasolConnector)
ConnectorRegistry.register("db2", DB2Connector, aliases=["ibm_db2"])
ConnectorRegistry.register("async_db2", AsyncDB2Connector, aliases=["async_ibm_db2"])
ConnectorRegistry.register("cosmosdb", CosmosDBConnector, aliases=["azure_cosmos"])
ConnectorRegistry.register(
    "async_cosmosdb", AsyncCosmosDBConnector, aliases=["async_azure_cosmos"]
)

__all__ = [
    "AlloyDBConnector",
    "ApacheCassandraConnector",
    "ArangoDBConnector",
    "AsyncApacheCassandraConnector",
    "AsyncArangoDBConnector",
    "AsyncAzureCosmosDBConnector",
    "AsyncBaseConnector",
    "AsyncCassandraConnector",
    "AsyncChDBConnector",
    "AsyncCosmosDBConnector",
    "AsyncCrateConnector",
    "AsyncCrateDBConnector",
    "AsyncDB2Connector",
    "AsyncExasolConnector",
    "AsyncGreptimeDBConnector",
    "AsyncIBMDB2Connector",
    "AsyncMaterializeConnector",
    "AsyncPrestoConnector",
    "AsyncPrestoDBConnector",
    "AsyncRisingWaveConnector",
    "AsyncSparkConnector",
    "AsyncSparkSQLConnector",
    "AsyncStarRocksConnector",
    "AsyncSurrealDBConnector",
    "AsyncTDengineConnector",
    "AthenaConnector",
    "AzureCosmosDBConnector",
    "BaseConnector",
    "BigQueryConnector",
    "CassandraConnector",
    "ChDBConnector",
    "ClickHouseConnector",
    "CloudflareD1Connector",
    "CockroachConnector",
    "ConnectionFailedError",
    "ConnectorError",
    "ConnectorRegistry",
    "CosmosDBConnector",
    "CouchbaseConnector",
    "CrateConnector",
    "CrateDBConnector",
    "D1Connector",
    "DB2Connector",
    "DataFusionConnector",
    "DatabricksConnector",
    "DremioConnector",
    "DriverNotInstalledError",
    "DruidConnector",
    "DuckDBConnector",
    "DynamoDBConnector",
    "ElasticsearchConnector",
    "ExasolConnector",
    "FireboltConnector",
    "GenericDBAPIConnector",
    "GreptimeDBConnector",
    "HANAConnector",
    "IBMDB2Connector",
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
    "SparkConnector",
    "SparkSQLConnector",
    "StarRocksConnector",
    "SupabaseConnector",
    "SurrealDBConnector",
    "TDengineConnector",
    "TeradataConnector",
    "TiDBConnector",
    "TimescaleConnector",
    "TrinoConnector",
    "VerticaConnector",
    "get_connector",
    "introspect_arangodb",
    "introspect_cassandra",
    "introspect_chdb",
    "introspect_clickhouse",
    "introspect_cosmosdb",
    "introspect_cratedb",
    "introspect_db2",
    "introspect_druid",
    "introspect_duckdb",
    "introspect_exasol",
    "introspect_greptimedb",
    "introspect_information_schema",
    "introspect_oracle",
    "introspect_saphana",
    "introspect_scylladb",
    "introspect_sparksql",
    "introspect_sqlite",
    "introspect_surrealdb",
    "introspect_tdengine",
    "introspect_via_sqlalchemy",
    "list_connectors",
    "register_connector",
]
