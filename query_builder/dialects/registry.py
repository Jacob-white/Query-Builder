"""Dialect registry: the ``DIALECTS`` map and its lookup/registration helpers."""

from __future__ import annotations

from typing import Any

from query_builder.dialects.base import BaseDialect
from query_builder.dialects.nosql import (
    ArangoDBDialect,
    BigtableDialect,
    CassandraDialect,
    CosmosDBDialect,
    CouchbaseDialect,
    DynamoDBPartiQLDialect,
    ElasticsearchDialect,
    FirestoreDialect,
    KdbDialect,
    MemgraphDialect,
    MongoDBSQLDialect,
    Neo4jDialect,
    NeptuneDialect,
    OpenSearchDialect,
    ScyllaDBDialect,
    SurrealDBDialect,
)
from query_builder.dialects.relational import (
    AlloyDBDialect,
    CockroachDialect,
    CrateDBDialect,
    D1Dialect,
    DB2Dialect,
    DerbyDialect,
    DuckDBDialect,
    ExasolDialect,
    FirebirdDialect,
    H2Dialect,
    InformixDialect,
    MaterializeDialect,
    MonetDBDialect,
    MSSQLDialect,
    MySQLDialect,
    NeonDialect,
    OceanBaseDialect,
    OracleDialect,
    PostgresDialect,
    RedshiftDialect,
    RisingWaveDialect,
    SAPHANADialect,
    SingleStoreDialect,
    SnowflakeDialect,
    SpannerDialect,
    SQLiteDialect,
    SupabaseDialect,
    SybaseDialect,
    TeradataDialect,
    TiDBDialect,
    TimescaleDialect,
    VerticaDialect,
    YugabyteDBDialect,
)
from query_builder.dialects.timeseries import (
    FlinkDialect,
    GreptimeDBDialect,
    InfluxDBDialect,
    KsqlDBDialect,
    KustoDialect,
    PrometheusDialect,
    PulsarDialect,
    QuestDBDialect,
    TDengineDialect,
    TimestreamDialect,
    VictoriaMetricsDialect,
)
from query_builder.dialects.vector import (
    ChromaDialect,
    LanceDBDialect,
    MilvusDialect,
    PineconeDialect,
    QdrantDialect,
    RedisSearchDialect,
    WeaviateDialect,
)
from query_builder.dialects.warehouse import (
    AthenaDialect,
    BigQueryDialect,
    ChDBDialect,
    ClickHouseDialect,
    ClickHouseNativeDialect,
    DatabricksDialect,
    DataFusionDialect,
    DorisDialect,
    DremioDialect,
    DrillDialect,
    DruidDialect,
    FireboltDialect,
    HiveDialect,
    ImpalaDialect,
    KyuubiDialect,
    PinotDialect,
    PolarsDialect,
    PrestoDialect,
    SparkSQLDialect,
    StarRocksDialect,
    TrinoDialect,
)

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
