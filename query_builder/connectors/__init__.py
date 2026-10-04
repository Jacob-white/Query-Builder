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
from query_builder.connectors.clickhouse_native import (
    AsyncClickHouseNativeConnector,
    ClickHouseNativeConnector,
)
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
from query_builder.connectors.derby import (
    AsyncDerbyConnector,
    DerbyConnector,
)
from query_builder.connectors.doris import (
    ApacheDorisConnector,
    AsyncApacheDorisConnector,
    AsyncDorisConnector,
    DorisConnector,
)
from query_builder.connectors.dremio import DremioConnector
from query_builder.connectors.drill import (
    ApacheDrillConnector,
    AsyncApacheDrillConnector,
    AsyncDrillConnector,
    DrillConnector,
)
from query_builder.connectors.druid import DruidConnector
from query_builder.connectors.duckdb import DuckDBConnector
from query_builder.connectors.dynamodb import DynamoDBConnector
from query_builder.connectors.elasticsearch import ElasticsearchConnector
from query_builder.connectors.exasol import (
    AsyncExasolConnector,
    ExasolConnector,
)
from query_builder.connectors.firebird import (
    AsyncFirebirdConnector,
    FirebirdConnector,
)
from query_builder.connectors.firebolt import FireboltConnector
from query_builder.connectors.generic import GenericDBAPIConnector
from query_builder.connectors.greptimedb import (
    AsyncGreptimeDBConnector,
    GreptimeDBConnector,
)
from query_builder.connectors.h2 import (
    AsyncH2Connector,
    H2Connector,
)
from query_builder.connectors.hive import (
    ApacheHiveConnector,
    AsyncApacheHiveConnector,
    AsyncHiveConnector,
    HiveConnector,
)
from query_builder.connectors.impala import (
    ApacheImpalaConnector,
    AsyncApacheImpalaConnector,
    AsyncImpalaConnector,
    ImpalaConnector,
)
from query_builder.connectors.influxdb import (
    InfluxDBConnector,
    IOxConnector,
)
from query_builder.connectors.informix import (
    AsyncIBMInformixConnector,
    AsyncInformixConnector,
    IBMInformixConnector,
    InformixConnector,
)
from query_builder.connectors.introspection import (
    introspect_arangodb,
    introspect_cassandra,
    introspect_chdb,
    introspect_clickhouse,
    introspect_clickhouse_native,
    introspect_cosmosdb,
    introspect_cratedb,
    introspect_db2,
    introspect_derby,
    introspect_doris,
    introspect_drill,
    introspect_druid,
    introspect_duckdb,
    introspect_exasol,
    introspect_firebird,
    introspect_greptimedb,
    introspect_h2,
    introspect_hive,
    introspect_impala,
    introspect_information_schema,
    introspect_informix,
    introspect_kdb,
    introspect_kyuubi,
    introspect_monetdb,
    introspect_neo4j,
    introspect_opensearch,
    introspect_oracle,
    introspect_saphana,
    introspect_scylladb,
    introspect_sparksql,
    introspect_sqlite,
    introspect_surrealdb,
    introspect_sybase,
    introspect_tdengine,
    introspect_via_sqlalchemy,
    introspect_yugabyte,
)
from query_builder.connectors.kdb import (
    AsyncKdbConnector,
    AsyncPyKXConnector,
    KdbConnector,
    PyKXConnector,
)
from query_builder.connectors.kyuubi import (
    ApacheKyuubiConnector,
    AsyncApacheKyuubiConnector,
    AsyncKyuubiConnector,
    KyuubiConnector,
)
from query_builder.connectors.materialize import (
    AsyncMaterializeConnector,
    MaterializeConnector,
)
from query_builder.connectors.monetdb import (
    AsyncMonetDBConnector,
    MonetDBConnector,
)
from query_builder.connectors.mongodb import (
    MongoDBAtlasSQLConnector,
    MongoDBConnector,
)
from query_builder.connectors.mssql import MSSQLConnector
from query_builder.connectors.mysql import MySQLConnector
from query_builder.connectors.neo4j import (
    AsyncNeo4jConnector,
    Neo4jConnector,
)
from query_builder.connectors.neon import NeonConnector
from query_builder.connectors.oceanbase import OceanBaseConnector
from query_builder.connectors.opensearch import (
    AsyncOpenSearchConnector,
    OpenSearchConnector,
)
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
from query_builder.connectors.sybase import (
    AsyncSAPASEConnector,
    AsyncSybaseConnector,
    SAPASEConnector,
    SybaseConnector,
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
from query_builder.connectors.yugabyte import (
    AsyncYugabyteConnector,
    AsyncYugabyteDBConnector,
    YugabyteConnector,
    YugabyteDBConnector,
)

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
ConnectorRegistry.register("elasticsearch", ElasticsearchConnector)
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

# Next-tier lakehouse, distributed HTAP, search, graph, and ultra-high-frequency time-series connectors
ConnectorRegistry.register("doris", DorisConnector, aliases=["apache_doris", "pydoris"])
ConnectorRegistry.register(
    "async_doris", AsyncDorisConnector, aliases=["async_apache_doris"]
)
ConnectorRegistry.register(
    "impala", ImpalaConnector, aliases=["apache_impala", "impyla"]
)
ConnectorRegistry.register(
    "async_impala", AsyncImpalaConnector, aliases=["async_apache_impala"]
)
ConnectorRegistry.register("hive", HiveConnector, aliases=["apache_hive", "pyhive"])
ConnectorRegistry.register(
    "async_hive", AsyncHiveConnector, aliases=["async_apache_hive"]
)
ConnectorRegistry.register("kyuubi", KyuubiConnector, aliases=["apache_kyuubi"])
ConnectorRegistry.register(
    "async_kyuubi", AsyncKyuubiConnector, aliases=["async_apache_kyuubi"]
)
ConnectorRegistry.register("drill", DrillConnector, aliases=["apache_drill", "pydrill"])
ConnectorRegistry.register(
    "async_drill", AsyncDrillConnector, aliases=["async_apache_drill"]
)
ConnectorRegistry.register("yugabyte", YugabyteDBConnector, aliases=["yugabytedb"])
ConnectorRegistry.register(
    "async_yugabyte", AsyncYugabyteDBConnector, aliases=["async_yugabytedb"]
)
ConnectorRegistry.register(
    "opensearch",
    OpenSearchConnector,
    aliases=["opensearch_sql", "opensearch_connector"],
)
ConnectorRegistry.register(
    "async_opensearch", AsyncOpenSearchConnector, aliases=["async_opensearch_sql"]
)
ConnectorRegistry.register("neo4j", Neo4jConnector, aliases=["cypher", "neo4j_sql"])
ConnectorRegistry.register("async_neo4j", AsyncNeo4jConnector, aliases=["async_cypher"])
ConnectorRegistry.register("kdb", KdbConnector, aliases=["kdb+", "pykx", "q"])
ConnectorRegistry.register(
    "async_kdb", AsyncKdbConnector, aliases=["async_kdb+", "async_pykx"]
)
ConnectorRegistry.register(
    "clickhouse_native",
    ClickHouseNativeConnector,
    aliases=["ch_native", "clickhouse_tcp"],
)
ConnectorRegistry.register(
    "async_clickhouse_native",
    AsyncClickHouseNativeConnector,
    aliases=["async_ch_native"],
)

# Phase 1 Enterprise Relational & Modern Embedded SQL Connectors
ConnectorRegistry.register("firebird", FirebirdConnector, aliases=["firebirdsql"])
ConnectorRegistry.register(
    "async_firebird", AsyncFirebirdConnector, aliases=["async_firebirdsql"]
)
ConnectorRegistry.register("monetdb", MonetDBConnector, aliases=["monet"])
ConnectorRegistry.register(
    "async_monetdb", AsyncMonetDBConnector, aliases=["async_monet"]
)
ConnectorRegistry.register("h2", H2Connector, aliases=["h2db"])
ConnectorRegistry.register("async_h2", AsyncH2Connector, aliases=["async_h2db"])
ConnectorRegistry.register("derby", DerbyConnector, aliases=["apache_derby"])
ConnectorRegistry.register(
    "async_derby", AsyncDerbyConnector, aliases=["async_apache_derby"]
)
ConnectorRegistry.register("sybase", SybaseConnector, aliases=["sap_ase", "ase"])
ConnectorRegistry.register(
    "async_sybase", AsyncSybaseConnector, aliases=["async_sap_ase", "async_ase"]
)
ConnectorRegistry.register("informix", InformixConnector, aliases=["ibm_informix"])
ConnectorRegistry.register(
    "async_informix", AsyncInformixConnector, aliases=["async_ibm_informix"]
)

__all__ = [
    "AlloyDBConnector",
    "ApacheCassandraConnector",
    "ApacheDorisConnector",
    "ApacheDrillConnector",
    "ApacheHiveConnector",
    "ApacheImpalaConnector",
    "ApacheKyuubiConnector",
    "ArangoDBConnector",
    "AsyncApacheCassandraConnector",
    "AsyncApacheDorisConnector",
    "AsyncApacheDrillConnector",
    "AsyncApacheHiveConnector",
    "AsyncApacheImpalaConnector",
    "AsyncApacheKyuubiConnector",
    "AsyncArangoDBConnector",
    "AsyncAzureCosmosDBConnector",
    "AsyncBaseConnector",
    "AsyncCassandraConnector",
    "AsyncChDBConnector",
    "AsyncClickHouseNativeConnector",
    "AsyncCosmosDBConnector",
    "AsyncCrateConnector",
    "AsyncCrateDBConnector",
    "AsyncDB2Connector",
    "AsyncDerbyConnector",
    "AsyncDorisConnector",
    "AsyncDrillConnector",
    "AsyncExasolConnector",
    "AsyncFirebirdConnector",
    "AsyncGreptimeDBConnector",
    "AsyncH2Connector",
    "AsyncHiveConnector",
    "AsyncIBMDB2Connector",
    "AsyncIBMInformixConnector",
    "AsyncImpalaConnector",
    "AsyncInformixConnector",
    "AsyncKdbConnector",
    "AsyncKyuubiConnector",
    "AsyncMaterializeConnector",
    "AsyncMonetDBConnector",
    "AsyncNeo4jConnector",
    "AsyncOpenSearchConnector",
    "AsyncPrestoConnector",
    "AsyncPrestoDBConnector",
    "AsyncPyKXConnector",
    "AsyncRisingWaveConnector",
    "AsyncSAPASEConnector",
    "AsyncSparkConnector",
    "AsyncSparkSQLConnector",
    "AsyncStarRocksConnector",
    "AsyncSurrealDBConnector",
    "AsyncSybaseConnector",
    "AsyncTDengineConnector",
    "AsyncYugabyteConnector",
    "AsyncYugabyteDBConnector",
    "AthenaConnector",
    "AzureCosmosDBConnector",
    "BaseConnector",
    "BigQueryConnector",
    "CassandraConnector",
    "ChDBConnector",
    "ClickHouseConnector",
    "ClickHouseNativeConnector",
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
    "DerbyConnector",
    "DorisConnector",
    "DremioConnector",
    "DrillConnector",
    "DriverNotInstalledError",
    "DruidConnector",
    "DuckDBConnector",
    "DynamoDBConnector",
    "ElasticsearchConnector",
    "ExasolConnector",
    "FirebirdConnector",
    "FireboltConnector",
    "GenericDBAPIConnector",
    "GreptimeDBConnector",
    "H2Connector",
    "HANAConnector",
    "HiveConnector",
    "IBMDB2Connector",
    "IBMInformixConnector",
    "IOxConnector",
    "ImpalaConnector",
    "InfluxDBConnector",
    "InformixConnector",
    "IntrospectionError",
    "KdbConnector",
    "KyuubiConnector",
    "MSSQLConnector",
    "MaterializeConnector",
    "MemSQLConnector",
    "MonetDBConnector",
    "MongoDBAtlasSQLConnector",
    "MongoDBConnector",
    "MySQLConnector",
    "N1QLConnector",
    "Neo4jConnector",
    "NeonConnector",
    "OceanBaseConnector",
    "OpenSearchConnector",
    "OracleConnector",
    "PinotConnector",
    "PolarsConnector",
    "PostgresConnector",
    "PrestoConnector",
    "PrestoDBConnector",
    "PyKXConnector",
    "QuestDBConnector",
    "RedshiftConnector",
    "RisingWaveConnector",
    "SAPASEConnector",
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
    "SybaseConnector",
    "TDengineConnector",
    "TeradataConnector",
    "TiDBConnector",
    "TimescaleConnector",
    "TrinoConnector",
    "VerticaConnector",
    "YugabyteConnector",
    "YugabyteDBConnector",
    "get_connector",
    "introspect_arangodb",
    "introspect_cassandra",
    "introspect_chdb",
    "introspect_clickhouse",
    "introspect_clickhouse_native",
    "introspect_cosmosdb",
    "introspect_cratedb",
    "introspect_db2",
    "introspect_derby",
    "introspect_doris",
    "introspect_drill",
    "introspect_druid",
    "introspect_duckdb",
    "introspect_exasol",
    "introspect_firebird",
    "introspect_greptimedb",
    "introspect_h2",
    "introspect_hive",
    "introspect_impala",
    "introspect_information_schema",
    "introspect_informix",
    "introspect_kdb",
    "introspect_kyuubi",
    "introspect_monetdb",
    "introspect_neo4j",
    "introspect_opensearch",
    "introspect_oracle",
    "introspect_saphana",
    "introspect_scylladb",
    "introspect_sparksql",
    "introspect_sqlite",
    "introspect_surrealdb",
    "introspect_sybase",
    "introspect_tdengine",
    "introspect_via_sqlalchemy",
    "introspect_yugabyte",
    "list_connectors",
    "register_connector",
]
