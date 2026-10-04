# Query-Builder Ecosystem Gap Audit & Universal Missing Connectors Blueprint
**Document Status**: Authoritative Engineering Specification & Support Blueprint  
**Target Publication**: `MISSING_CONNECTORS_PLAN.md`  
**Author**: teamwork_preview_explorer  
**Date**: October 2026  

---

## 1. Executive Summary & Ecosystem Baseline

Query-Builder currently provides a production-grade query compilation, AST security validation, execution middleware, and schema introspection framework supporting **65 database and query engines** registered in `query_builder/connectors/registry.py` and exported in `query_builder/connectors/__init__.py`. 

The entire Python test suite executes with **100% statement and 100% branch coverage** (581 passed tests across 10,200 statements and 3,004 branches), and the accompanying headless React library (`@jacob-white/query-builder-react`) maintains **100% statement, line, function, and branch coverage** (399 passed tests across 31 test suites).

### 1.1 Existing Connector Inventory (65 Baseline Connectors)

The 65 active connectors are categorized below by their operational archetype:

| Category Archetype | Existing Supported Engines | Count |
| :--- | :--- | :--- |
| **Traditional & Enterprise Relational** | PostgreSQL, MySQL, Microsoft SQL Server (MSSQL), SQLite, Oracle, IBM DB2, SAP HANA, Teradata, Exasol, Vertica | 10 |
| **Cloud Data Warehouses & Analytics** | Snowflake, Google BigQuery, Amazon Redshift, Databricks, AWS Athena, Firebolt | 6 |
| **Modern Distributed & HTAP SQL** | CockroachDB, YugabyteDB, TiDB, SingleStore, OceanBase, Google Cloud Spanner, Google Cloud AlloyDB | 7 |
| **Serverless & Managed Cloud SQL** | Neon, Supabase, Cloudflare D1 | 3 |
| **Lakehouse & Distributed MPP Engines** | Apache Spark SQL, PrestoDB, Trino, Apache Doris, Apache Impala, Apache Hive, Apache Kyuubi, Apache Drill, Dremio | 9 |
| **Embedded & Columnar Engines** | DuckDB, Polars, Apache Arrow DataFusion, chDB (embedded ClickHouse) | 4 |
| **Real-Time OLAP & Streaming SQL** | ClickHouse (HTTP), ClickHouse Native (TCP), StarRocks, Apache Druid, Apache Pinot, Materialize, RisingWave, CrateDB | 8 |
| **Time-Series & Financial IoT** | TimescaleDB, QuestDB, GreptimeDB, TDengine, InfluxDB (IOx), Kdb+ (q / PyKX) | 6 |
| **NoSQL, Multi-Model, Search & Graph** | MongoDB Atlas SQL, Amazon DynamoDB (PartiQL), Apache Cassandra, ScyllaDB (CQL), Couchbase (N1QL), Elasticsearch SQL, OpenSearch SQL, Neo4j (Cypher), SurrealDB (SurrealQL), ArangoDB (AQL), Azure Cosmos DB (SQL API) | 11 |
| **Generic & Base Protocol** | Generic DB-API 2.0 (`generic`) | 1 |
| **Total Baseline Engines** | **Active Unique Synchronous Connector Classes** | **65** |

In addition, 25 high-demand connectors currently implement dedicated asynchronous counterparts (`AsyncBaseConnector`), including `AsyncSparkSQLConnector`, `AsyncClickHouseNativeConnector`, `AsyncNeo4jConnector`, `AsyncKdbConnector`, `AsyncOpenSearchConnector`, and others.

---

## 2. Missing Connector Taxonomy Gap Audit

Despite supporting 65 connectors, modern enterprise data stacks and AI applications frequently leverage specialized storage engines that fall outside the traditional relational and lakehouse paradigms. To establish universal coverage, Query-Builder has conducted an audit across **5 vital architectural domains** identifying **24 missing engines**:

1. **Vector & AI Data Stores** (6 engines): Pinecone, Qdrant, Weaviate, Milvus, ChromaDB, LanceDB
2. **Graph & Log/KQL Engines** (5 engines): Memgraph, Amazon Neptune, Azure Data Explorer (Kusto/KQL), VictoriaMetrics (MetricsQL), Prometheus (PromQL)
3. **Streaming SQL & Event Gateways** (3 engines): ksqlDB, Apache Flink SQL, Apache Pulsar SQL
4. **Enterprise & Legacy Relational SQL** (6 engines): Firebird, IBM Informix, Sybase / SAP ASE, MonetDB, Apache Derby, H2
5. **Cloud NoSQL & Key-Value Engines** (4 engines): Google Cloud Firestore, Google Cloud Bigtable, AWS Timestream, Redis / RediSearch

Below is the exhaustive audit for each individual engine across the 5 domains.

---

### Category 1: Vector & AI Data Stores

Vector databases store high-dimensional embeddings and execute approximate nearest neighbor (ANN) vector searches combined with boolean metadata filtering.

#### 1. Pinecone
- **Category**: Managed Serverless Vector Database
- **Primary Use Case**: Semantic search, RAG pipelines, recommendation systems with managed cloud infrastructure.
- **Query Language / API Model**: JSON/REST filter expressions combined with vector distance ranking.
  ```json
  POST /query
  {"vector": [0.12, -0.45, ...], "filter": {"genre": {"$eq": "documentary"}, "year": {"$gte": 2020}}, "topK": 20, "includeMetadata": true}
  ```
- **Driver Transport & Python Client**: `pinecone-client` (REST over HTTPS + gRPC data plane).
- **Schema Introspection Feasibility**: High. `client.list_indexes()` enumerates indexes; `client.describe_index(name)` exposes dimension, metric (`cosine`, `dotproduct`, `euclidean`), and status. Metadata schema is dynamic JSON; the connector can sample representative vector vectors via `index.query` to discover active payload keys and infer types.
- **Implementation Complexity Tier**: **Tier 3** (Custom cursor adapter mapping SQL `WHERE` clauses to Pinecone JSON filter predicates; result normalization from vector matches to tabular rows).

#### 2. Qdrant
- **Category**: Vector Search Engine & Vector Database (Rust core)
- **Primary Use Case**: High-scale semantic retrieval, multimodal vector indexing, hybrid dense/sparse search.
- **Query Language / API Model**: REST / gRPC JSON payload filter DSL. Supports boolean conditions (`must`, `should`, `must_not`) and field filters (`match`, `range`, `values`).
  ```json
  POST /collections/{name}/points/query
  {"filter": {"must": [{"key": "status", "match": {"value": "active"}}]}, "limit": 25}
  ```
- **Driver Transport & Python Client**: `qdrant-client` (REST / HTTP/2 or gRPC via `grpcio`).
- **Schema Introspection Feasibility**: High. `client.get_collections()` lists collections; `client.get_collection(name)` exposes vector size, distance metric (`Cosine`, `Euclid`, `Dot`), and payload index schema (`collection.payload_schema`). Dynamic keys discovered via `client.scroll(limit=5)`.
- **Implementation Complexity Tier**: **Tier 3** (Translate SQL expressions to nested Qdrant JSON filter objects; unpack `ScoredPoint` objects into tabular records).

#### 3. Weaviate
- **Category**: Cloud-Native Modular Vector Database & Knowledge Graph
- **Primary Use Case**: Hybrid vector/BM25 search, generative feedback loops, structured multimodal object storage.
- **Query Language / API Model**: GraphQL (`{ Get { Document(where: {...}) { id title } } }`), REST, and Weaviate v4 Python Collections API (`collection.query.fetch_objects(filters=...)`).
- **Driver Transport & Python Client**: `weaviate-client` (v4+ combines gRPC for high-throughput batch/query with REST for schema definitions).
- **Schema Introspection Feasibility**: Outstanding. Weaviate maintains an explicit, strongly typed class/collection schema catalog (`client.collections.list_all()` or REST `GET /v1/schema`). Classes define properties with explicit types (`text`, `int`, `boolean`, `date`, `number`, `uuid`), nullability, and index configurations.
- **Implementation Complexity Tier**: **Tier 3** (Translate SQL projection and filter AST to Weaviate `Filter` objects; unpack gRPC `WeaviateObject` records).

#### 4. Milvus
- **Category**: Distributed Cloud-Native Vector Database (LF AI & Data Foundation)
- **Primary Use Case**: Billion-scale vector search, enterprise embeddings retrieval, multimodal analytics.
- **Query Language / API Model**: SQL-like boolean predicate syntax passed to scalar filter engine:
  ```python
  client.query(
      collection_name="docs",
      filter="category == 'tech' and read_count > 100",
      output_fields=["id", "title", "read_count"],
  )
  ```
- **Driver Transport & Python Client**: `pymilvus` (gRPC over HTTP/2, Milvus Lite embedded).
- **Schema Introspection Feasibility**: Outstanding. Explicit schema catalog via `client.list_collections()` and `client.describe_collection(name)`. Yields collection fields, field data types (`DataType.INT64`, `DataType.VARCHAR`, `DataType.FLOAT_VECTOR`), primary key identification (`is_primary=True`), dimension, and partition keys.
- **Implementation Complexity Tier**: **Tier 3** (Milvus boolean expression translator; gRPC result unpacking).

#### 5. ChromaDB
- **Category**: In-Process & Client-Server AI Embedding Database
- **Primary Use Case**: Developer-first local LLM memory, local RAG pipelines, notebook prototyping.
- **Query Language / API Model**: Python SDK / REST API with dictionary query filters:
  ```python
  collection.get(
      where={"category": {"$eq": "news"}},
      include=["metadatas", "documents"],
      limit=50,
  )
  ```
- **Driver Transport & Python Client**: `chromadb` (In-process SQLite/DuckDB storage or HTTP REST client).
- **Schema Introspection Feasibility**: Good. `client.list_collections()` returns collections; `collection.get(limit=1)` samples metadata dictionaries to infer column names and Python types (`str`, `int`, `float`, `bool`).
- **Implementation Complexity Tier**: **Tier 3** (SQL filter to Chroma `$eq`/`$and` dictionary mapping; adapter unpacking documents/metadata).

#### 6. LanceDB
- **Category**: Developer-Friendly Serverless Vector Database built on Apache Arrow & Lance Columnar Format
- **Primary Use Case**: Multimodal vector search, embedded on-disk disk-ann indexing, zero-copy Arrow data pipelines.
- **Query Language / API Model**: PyArrow-backed SQL expressions and vector search:
  ```python
  tbl.search(vector).where("price < 50.0 AND in_stock = true").limit(20).to_arrow()
  ```
- **Driver Transport & Python Client**: `lancedb` (In-process native Lance/Arrow engine or LanceDB Cloud REST).
- **Schema Introspection Feasibility**: Outstanding. Built directly on Apache Arrow! `db.table_names()` lists tables; `table.schema` returns the exact `pyarrow.Schema` with typed fields, nullability, and metadata.
- **Implementation Complexity Tier**: **Tier 2/3** (Arrow table rowset conversion; Lance SQL filter execution).

---

### Category 2: Graph & Log/KQL Engines

Graph databases manage interconnected nodes and relationships, while log/time-series engines execute domain-specific languages (KQL, PromQL, MetricsQL) optimized for append-only events.

#### 7. Memgraph
- **Category**: In-Memory OpenCypher Graph Database
- **Primary Use Case**: Real-time graph analytics, cyber fraud detection, network topology, high-throughput streaming graph updates.
- **Query Language / API Model**: OpenCypher (fully compatible with Neo4j Cypher syntax):
  ```cypher
  MATCH (n:Account)-[r:TRANSFERRED]->(m:Account)
  WHERE n.balance > 10000
  RETURN n.id AS src, m.id AS tgt, r.amount AS amount
  LIMIT 50;
  ```
- **Driver Transport & Python Client**: Bolt protocol (`neo4j` Python driver or `gqlalchemy` / `mgclient`). Can connect over standard Bolt port 7687.
- **Schema Introspection Feasibility**: High. `SHOW CONSTRAINT INFO;`, `SHOW INDEX INFO;`, `CALL mg.labels()`, `CALL mg.relationship_types()`, and label property extraction via sampling.
- **Implementation Complexity Tier**: **Tier 2** (Cypher dialect; Bolt protocol cursor adapter).

#### 8. Amazon Neptune
- **Category**: Managed Cloud Graph Database Service (AWS)
- **Primary Use Case**: Enterprise knowledge graphs, identity resolution, social networks, recommendation engines.
- **Query Language / API Model**: openCypher endpoint (HTTP REST `/openCypher` or Bolt), Apache TinkerPop Gremlin (WebSocket), W3C SPARQL. openCypher is the modern standard for tabular entity querying.
- **Driver Transport & Python Client**: Bolt (`neo4j` Python driver configured with SSL/IAM) or HTTPS REST (`requests`/`boto3` Neptune Data API).
- **Schema Introspection Feasibility**: High. openCypher endpoints support `CALL db.labels()`, `CALL db.relationshipTypes()`, `CALL db.propertyKeys()`, and Neptune summary API (`GET /openCypher/status`).
- **Implementation Complexity Tier**: **Tier 2/3** (openCypher dialect mapping; SigV4 authentication; Bolt/HTTPS adapter).

#### 9. Azure Data Explorer (ADX / Kusto / KQL)
- **Category**: Distributed Big Data Log & Telemetry Analytics Engine (Microsoft Azure)
- **Primary Use Case**: High-velocity observability logs, security event monitoring (SIEM/Sentinel), IoT telemetry, time-series streaming.
- **Query Language / API Model**: Kusto Query Language (KQL):
  ```kql
  SecurityAlert
  | where Severity == "High" and TimeGenerated > ago(7d)
  | project AlertName, Computer, TimeGenerated
  | take 100
  ```
- **Driver Transport & Python Client**: `azure-kusto-data` (HTTPS REST with Microsoft Entra ID / token authentication).
- **Schema Introspection Feasibility**: Outstanding. Native management commands: `.show database schema as json` or `.show tables`, `.show table TableName schema as json`. Exposes exact column names, CSL types (`string`, `datetime`, `int`, `long`, `real`, `dynamic`), and docstrings.
- **Implementation Complexity Tier**: **Tier 2** (KQL pipeline translation from QuerySpec; Kusto response dataset cursor adapter).

#### 10. VictoriaMetrics (MetricsQL)
- **Category**: Scalable Time-Series Database & Monitoring Solution
- **Primary Use Case**: High-cardinality metrics storage, Kubernetes cluster observability, long-term Prometheus retention.
- **Query Language / API Model**: MetricsQL (backward-compatible superset of PromQL with subqueries and rollups) via HTTP REST (`/api/v1/query`, `/api/v1/query_range`, `/api/v1/export`).
  ```promql
  rate(http_requests_total{status=~"5.."}[5m]) > 0.05
  ```
- **Driver Transport & Python Client**: HTTP REST (`requests`, `httpx`).
- **Schema Introspection Feasibility**: High. Metric metadata discovery via `/api/v1/label/__name__/values` (returns all active metric names as "tables"), `/api/v1/labels` (returns dimension keys), and `/api/v1/series` (returns label sets).
- **Implementation Complexity Tier**: **Tier 2** (Translate SQL projection/filters to MetricsQL selector syntax; convert matrix/vector responses into tabular timestamp-metric rows).

#### 11. Prometheus (PromQL)
- **Category**: Open-Source Systems Monitoring & Alerting Toolkit
- **Primary Use Case**: Infrastructure monitoring, microservice metrics, real-time alerting.
- **Query Language / API Model**: PromQL (Prometheus Query Language) via HTTP API (`/api/v1/query`, `/api/v1/query_range`).
- **Driver Transport & Python Client**: HTTP REST (`prometheus-api-client`, `requests`, `httpx`).
- **Schema Introspection Feasibility**: High. `/api/v1/label/__name__/values` (metric names), `/api/v1/metadata` (metric type: counter, gauge, histogram, summary, plus help text), `/api/v1/labels` (label dimensions).
- **Implementation Complexity Tier**: **Tier 2** (PromQL selector translation; time-series matrix to tabular rowset adapter).

---

### Category 3: Streaming SQL & Event Gateways

Streaming SQL engines execute continuous and pull queries against unbounded event streams and materialized changelogs.

#### 12. ksqlDB
- **Category**: Event Streaming Database for Apache Kafka
- **Primary Use Case**: Real-time stream processing, streaming ETL, materialized state views over Kafka topics.
- **Query Language / API Model**: ksqlDB SQL (Continuous queries with `EMIT CHANGES`; pull queries against materialized tables):
  ```sql
  SELECT user_id, total_orders FROM user_order_totals WHERE user_id = 'user_123';
  ```
- **Driver Transport & Python Client**: ksqlDB HTTP/2 REST API (`/query`, `/query-stream`, `/ksql`) via `requests`, `httpx`, or `ksqldb-python`.
- **Schema Introspection Feasibility**: Outstanding. `SHOW STREAMS;`, `SHOW TABLES;`, `DESCRIBE <stream_or_table>;`. Exposes topic name, serialization format (JSON, AVRO, PROTOBUF), schema fields (`VARCHAR`, `BIGINT`, `DOUBLE`, `ARRAY`, `STRUCT`).
- **Implementation Complexity Tier**: **Tier 2** (ksqlDB HTTP query runner; pull query result adapter).

#### 13. Apache Flink SQL
- **Category**: Unified Batch & Real-Time Stream Processing Framework
- **Primary Use Case**: Complex event processing, low-latency streaming aggregations, dynamic table transformations.
- **Query Language / API Model**: Apache Flink SQL (ANSI-compliant SQL with temporal table joins, window functions, and match recognition).
- **Driver Transport & Python Client**: Flink SQL Gateway REST API (`/v1/sessions/.../statements`) or JDBC Driver (`org.apache.flink.table.client`).
- **Schema Introspection Feasibility**: Outstanding. ANSI catalog: `SHOW CATALOGS;`, `SHOW DATABASES;`, `SHOW TABLES;`, `DESCRIBE <table_name>;`, `SHOW CREATE TABLE <table_name>;`.
- **Implementation Complexity Tier**: **Tier 2** (Flink SQL Gateway session lifecycle management; asynchronous statement polling adapter).

#### 14. Apache Pulsar SQL
- **Category**: Distributed Messaging & Event Streaming Platform with Interactive SQL
- **Primary Use Case**: Direct SQL queries over tiered bookkeeper storage and historical topic backlogs.
- **Query Language / API Model**: ANSI SQL executed via Pulsar SQL (Trino/Presto coordinator bundled with Pulsar).
- **Driver Transport & Python Client**: Presto/Trino DB-API wire protocol (`trino-python-client` / `pulsar-client`) targeting Pulsar SQL port (typically 8081).
- **Schema Introspection Feasibility**: Outstanding. Standard Presto/Trino catalog commands: `SHOW SCHEMAS FROM pulsar;`, `SHOW TABLES FROM pulsar.<tenant_namespace>;`, `DESCRIBE pulsar.<tenant_namespace>.<topic>;`. Introspects message fields based on the Pulsar Schema Registry (Avro, JSON, Protobuf).
- **Implementation Complexity Tier**: **Tier 1/2** (Presto/Trino protocol connector pre-configured for Pulsar catalog).

---

### Category 4: Enterprise & Legacy Relational SQL

Enterprise relational engines implement standard or dialect-specific SQL with traditional catalog tables and DB-API drivers.

#### 15. Firebird
- **Category**: Open-Source Relational Database Management System
- **Primary Use Case**: Embedded desktop applications, ERP and accounting backends, enterprise transactional systems.
- **Query Language / API Model**: Firebird SQL (ANSI-SQL with `FIRST N SKIP M` or `ROWS N TO M` pagination).
  ```sql
  SELECT FIRST 50 SKIP 0 id, name, balance FROM accounts WHERE status = ? ORDER BY id;
  ```
- **Driver Transport & Python Client**: `firebird-driver` (official DB-API 2.0 driver for Firebird 3.0+) or legacy `fdb`.
- **Schema Introspection Feasibility**: Complete. System catalog tables `RDB$RELATIONS`, `RDB$RELATION_FIELDS`, `RDB$FIELDS`, `RDB$RELATION_CONSTRAINTS`, `RDB$INDICES`.
- **Implementation Complexity Tier**: **Tier 1** (Standard DB-API 2.0 relational connector).

#### 16. IBM Informix
- **Category**: Enterprise Relational Database (IBM Informix Dynamic Server - IDS)
- **Primary Use Case**: High-volume OLTP, telecommunications billing, embedded industrial time-series.
- **Query Language / API Model**: Informix SQL (supports `SKIP M FIRST N` syntax):
  ```sql
  SELECT SKIP 0 FIRST 50 id, username FROM users WHERE active = 'Y';
  ```
- **Driver Transport & Python Client**: `ibm_db` / `ibm_db_dbi` (DB-API 2.0 compliant).
- **Schema Introspection Feasibility**: Complete. System catalog tables `systables`, `syscolumns`, `sysconstraints`, `sysindexes`, `sysreferences`.
- **Implementation Complexity Tier**: **Tier 1** (Standard DB-API 2.0 relational connector).

#### 17. Sybase / SAP ASE (Adaptive Server Enterprise)
- **Category**: Enterprise High-Performance Relational Database
- **Primary Use Case**: Wall Street financial trading systems, risk management, legacy ERP databases.
- **Query Language / API Model**: Transact-SQL (T-SQL). Pagination via `TOP N`, window functions `ROW_NUMBER()`, or temp table cursors.
- **Driver Transport & Python Client**: `pyodbc` (with FreeTDS ODBC driver) or `sqlanydb` / `sybpydb`.
- **Schema Introspection Feasibility**: Complete. System tables `sysobjects`, `syscolumns`, `systypes`, `syskeys`, `sysconstraints`, `sysreferences`.
- **Implementation Complexity Tier**: **Tier 1** (Standard DB-API 2.0 relational connector).

#### 18. MonetDB
- **Category**: Column-Store Analytical Database Management System
- **Primary Use Case**: High-speed business intelligence, data warehousing, computational scientific analysis.
- **Query Language / API Model**: MonetDB SQL (ANSI-SQL with standard `LIMIT N OFFSET M` pagination).
- **Driver Transport & Python Client**: `pymonetdb` (pure Python DB-API 2.0 driver).
- **Schema Introspection Feasibility**: Complete. System catalog views `sys.tables`, `sys.columns`, `sys.keys`, `sys.keycolumns`, `sys.fkeys`.
- **Implementation Complexity Tier**: **Tier 1** (Pure Python DB-API 2.0 columnar relational connector).

#### 19. Apache Derby
- **Category**: Pure Java Relational Database Engine (formerly IBM Cloudscape)
- **Primary Use Case**: Embedded Java applications, desktop clients, local testing environments.
- **Query Language / API Model**: ANSI SQL (supports SQL:2008 standard `OFFSET M ROWS FETCH NEXT N ROWS ONLY`).
- **Driver Transport & Python Client**: `jaydebeapi` (JDBC `org.apache.derby.jdbc.ClientDriver`) or DRDA network protocol.
- **Schema Introspection Feasibility**: Complete. System catalogs `SYS.SYSTABLES`, `SYS.SYSCOLUMNS`, `SYS.SYSCONSTRAINTS`, `SYS.SYSKEYS`.
- **Implementation Complexity Tier**: **Tier 1** (Standard DB-API 2.0 / JDBC bridge).

#### 20. H2
- **Category**: Fast In-Memory & Embedded Java SQL Database
- **Primary Use Case**: Lightweight embedded applications, unit test fixtures, microservice prototyping.
- **Query Language / API Model**: ANSI SQL (supports `LIMIT N OFFSET M` and `OFFSET M ROWS FETCH NEXT N ROWS ONLY`).
- **Driver Transport & Python Client**: PostgreSQL wire protocol server mode (`psycopg` / `pg8000`) or `jaydebeapi` (JDBC `org.h2.Driver`).
- **Schema Introspection Feasibility**: Complete. ANSI `INFORMATION_SCHEMA.TABLES`, `INFORMATION_SCHEMA.COLUMNS`, `INFORMATION_SCHEMA.TABLE_CONSTRAINTS`.
- **Implementation Complexity Tier**: **Tier 1** (Standard DB-API 2.0 / PostgreSQL wire compatible).

---

### Category 5: Cloud NoSQL & Key-Value Engines

Cloud-native NoSQL and key-value databases feature non-relational storage architectures with flexible schemas and specialized query interfaces.

#### 21. Google Cloud Firestore
- **Category**: Serverless Cloud Document Database (Google Cloud)
- **Primary Use Case**: Mobile/web backends, user profiles, real-time reactive sync applications.
- **Query Language / API Model**: Structured Document Queries (`collection.where(field, op, val).order_by(field).limit(N).offset(N).stream()`).
- **Driver Transport & Python Client**: `google-cloud-firestore` (gRPC / HTTP/2 with Google Application Default Credentials).
- **Schema Introspection Feasibility**: High. `client.collections()` discovers root collections; sampling documents (`collection.limit(5).stream()`) extracts active field names, data types, and primary key (`__name__` / document ID).
- **Implementation Complexity Tier**: **Tier 3** (SQL WHERE clause to Firestore filter builder; gRPC DocumentSnapshot rowset adapter).

#### 22. Google Cloud Bigtable
- **Category**: High-Performance NoSQL Wide-Column Store (Google Cloud)
- **Primary Use Case**: Low-latency ad tech data, financial tick streams, IoT telemetry, large-scale sequential keys.
- **Query Language / API Model**: Row key ranges, prefix filters, column family qualifiers (`table.read_rows(filter_=RowFilterChain([...]))`) or GoogleSQL for Bigtable.
- **Driver Transport & Python Client**: `google-cloud-bigtable` (gRPC binary transport).
- **Schema Introspection Feasibility**: High. `table.list_column_families()` extracts column families; sampling rows extracts column qualifiers and cell timestamps.
- **Implementation Complexity Tier**: **Tier 3** (Row key filter translation; wide-column cells to flat tabular rowset adapter).

#### 23. AWS Timestream
- **Category**: Serverless Managed Time-Series Database (AWS)
- **Primary Use Case**: Industrial telemetry, DevOps server monitoring, connected vehicle data.
- **Query Language / API Model**: AWS Timestream SQL (ANSI-92 SQL subset with time-series functions: `SELECT time, measure_value::double FROM "db"."table" WHERE time > ago(1d)`).
- **Driver Transport & Python Client**: `boto3` (`timestream-query` client `query(QueryString=...)`).
- **Schema Introspection Feasibility**: Outstanding. `timestream-write` API lists databases and tables (`list_databases()`, `list_tables()`); query catalog supports `SHOW MEASURES FROM "db"."table"` and `DESCRIBE "db"."table"`.
- **Implementation Complexity Tier**: **Tier 2** (boto3 JSON REST client; paginated Timestream Datum/Row cursor adapter).

#### 24. Redis / RediSearch
- **Category**: In-Memory Key-Value & Secondary Index Search Engine
- **Primary Use Case**: Ultra-low-latency real-time search, secondary indexing over Redis Hashes and JSON documents, vector similarity.
- **Query Language / API Model**: RediSearch Query Syntax (`FT.SEARCH index "@category:{electronics} @price:[0 500]" LIMIT 0 10`).
- **Driver Transport & Python Client**: `redis` / `redis-py` (`client.ft(index).search(query)`).
- **Schema Introspection Feasibility**: Outstanding. `FT._LIST` returns all RediSearch indexes; `FT.INFO <index>` exposes exact indexed schema fields, field types (`TEXT`, `NUMERIC`, `TAG`, `VECTOR`, `GEO`), field weights, and indexing options.
- **Implementation Complexity Tier**: **Tier 2/3** (Translate SQL expressions to RediSearch query syntax; unpack Redis Document objects into tabular rows).

---

### 2.2 Comparative Taxonomy Matrix Table

| Engine | Category Domain | Primary Query Lang / Model | Driver Transport | Client Package | Schema Catalog | Complexity Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **Pinecone** | Vector & AI | JSON Filter + Vector Sim | HTTPS / gRPC | `pinecone-client` | Dynamic (Sample) | **Tier 3** |
| **Qdrant** | Vector & AI | JSON Payload Filter | HTTP/2 / gRPC | `qdrant-client` | Explicit + Dynamic | **Tier 3** |
| **Weaviate** | Vector & AI | GraphQL / Collections API | gRPC / REST | `weaviate-client` | Explicit Strong Schema | **Tier 3** |
| **Milvus** | Vector & AI | Boolean Scalar Expr | gRPC | `pymilvus` | Explicit Schema | **Tier 3** |
| **ChromaDB** | Vector & AI | JSON Where Filter | In-Process / REST | `chromadb` | Dynamic (Sample) | **Tier 3** |
| **LanceDB** | Vector & AI | PyArrow SQL Filter | Native Arrow | `lancedb` | Apache Arrow Schema | **Tier 2/3** |
| **Memgraph** | Graph & Log | openCypher | Bolt Protocol | `neo4j` / `mgclient` | Constraints & Labels | **Tier 2** |
| **Amazon Neptune** | Graph & Log | openCypher / Gremlin | Bolt / HTTPS REST | `neo4j` / `boto3` | Summary / Labels | **Tier 2/3** |
| **Azure Data Explorer** | Graph & Log | KQL (Kusto Query Lang) | HTTPS REST | `azure-kusto-data` | Explicit Schema (.show) | **Tier 2** |
| **VictoriaMetrics** | Graph & Log | MetricsQL | HTTP REST | `requests` / `httpx` | Label / Series Metadata | **Tier 2** |
| **Prometheus** | Graph & Log | PromQL | HTTP REST | `requests` / `httpx` | Label / Metadata API | **Tier 2** |
| **ksqlDB** | Streaming SQL | ksqlDB SQL (Pull Queries) | HTTP/2 REST | `requests` / `httpx` | Explicit (DESCRIBE) | **Tier 2** |
| **Apache Flink SQL** | Streaming SQL | ANSI Flink SQL | SQL Gateway REST | `requests` / `httpx` | Explicit (SHOW/DESCRIBE) | **Tier 2** |
| **Apache Pulsar SQL** | Streaming SQL | ANSI SQL (Trino Wire) | Presto/Trino Wire | `trino` | Schema Registry | **Tier 1/2** |
| **Firebird** | Enterprise Relational | Firebird SQL (FIRST/SKIP) | DB-API 2.0 Wire | `firebird-driver` | System Tables (RDB$) | **Tier 1** |
| **IBM Informix** | Enterprise Relational | Informix SQL (SKIP/FIRST)| DB-API 2.0 Wire | `ibm_db` | System Catalogs (sys) | **Tier 1** |
| **Sybase / SAP ASE** | Enterprise Relational | Transact-SQL (T-SQL) | DB-API / FreeTDS | `pyodbc` / `sqlanydb` | System Catalogs (sys) | **Tier 1** |
| **MonetDB** | Enterprise Relational | MonetDB SQL | DB-API 2.0 Wire | `pymonetdb` | System Catalogs (sys) | **Tier 1** |
| **Apache Derby** | Enterprise Relational | ANSI SQL (OFFSET/FETCH) | DB-API / JDBC | `jaydebeapi` | System Catalogs (SYS) | **Tier 1** |
| **H2** | Enterprise Relational | ANSI SQL (LIMIT/OFFSET) | Postgres Wire / JDBC | `psycopg` / `jaydebeapi`| INFORMATION_SCHEMA | **Tier 1** |
| **Google Firestore** | Cloud NoSQL & KV | Structured Query API | gRPC / HTTP/2 | `google-cloud-firestore`| Dynamic (Sample) | **Tier 3** |
| **Google Bigtable** | Cloud NoSQL & KV | Row Key / Prefix Filter | gRPC Binary | `google-cloud-bigtable` | Column Families | **Tier 3** |
| **AWS Timestream** | Cloud NoSQL & KV | Timestream SQL | HTTPS REST | `boto3` | Explicit (SHOW MEASURES)| **Tier 2** |
| **Redis / RediSearch** | Cloud NoSQL & KV | RediSearch Query Syntax | RESP Binary Wire | `redis` | Explicit (FT.INFO) | **Tier 2/3** |

---

## 3. Universal Architecture & Connector Blueprint

To seamlessly incorporate all 24 missing engines into Query-Builder without breaking API contracts or degrading developer experience, Query-Builder employs a four-layer universal connector architecture:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        QuerySpec Execution Pipeline                    │
│   (QueryCompiler -> validate_sql_ast -> MiddlewarePipeline Interceptors)│
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
       Relational / SQL Engines         Non-Standard / NoSQL Engines
     (Firebird, MonetDB, H2, etc.)    (Pinecone, Qdrant, KQL, PromQL)
                     │                               │
                     │                 ┌─────────────┴─────────────┐
                     │                 ▼                           ▼
                     │        Query Translation Layer     Specialized Cursor Adapter
                     │       (query_builder/dialects.py) (DB-API Protocol Emulation)
                     │                 │                           │
                     └─────────────────┼───────────────────────────┘
                                       ▼
                       ┌───────────────────────────────┐
                       │   Connection & Driver Plane   │
                       │    BaseConnector / AsyncBase  │
                       └───────────────┬───────────────┘
                                       ▼
                       ┌───────────────────────────────┐
                       │  Schema Introspection Engine  │
                       │  (query_builder/introspection)│
                       └───────────────────────────────┘
```

### 3.1 Dialect Translation & AST Compilation Strategy (`query_builder/dialects.py`)

Each new connector binds to a dedicated dialect class inheriting from `BaseDialect`. The dialect governs:
1. **Identifier Quoting**: Double quotes (`"col"` for Firebird, MonetDB, Derby, H2), backticks (`` `col` `` for Flink SQL, RediSearch), or square brackets (`[col]` for Sybase ASE).
2. **Parameter Placeholders**:
   - Positional `?`: Firebird, MonetDB, Derby, H2, Timestream, LanceDB.
   - Positional `%s`: Informix, Flink SQL.
   - Named or dollar `$param`: Memgraph, Neptune (openCypher).
   - Inlined / Sanitized expressions: KQL, PromQL, RediSearch.
3. **Pagination & Windowing Syntax**:
   - `format_limit_offset(limit, offset)`:
     - Firebird: `SELECT FIRST %s SKIP %s ...`
     - Informix: `SELECT SKIP %s FIRST %s ...`
     - Derby: `OFFSET %s ROWS FETCH NEXT %s ROWS ONLY`
     - MonetDB / H2: `LIMIT %s OFFSET %s`
     - KQL: `| take {limit}`
     - openCypher: `SKIP {offset} LIMIT {limit}`
     - RediSearch: `LIMIT {offset} {limit}`
4. **Introspection Query Generation**: Dialect methods `inspect_tables_query`, `inspect_columns_query`, `inspect_primary_keys_query`, and `inspect_foreign_keys_query`.

### 3.2 Specialized Cursor Adapter Architecture (`_CursorAdapter` Pattern)

For engines lacking a native Python DB-API 2.0 cursor (REST APIs, gRPC streaming, vector SDKs, NoSQL services), Query-Builder implements the `_CursorAdapter` pattern. This guarantees that `BaseConnector`'s default `execute()`, `execute_raw()`, and `test_connection()` routines function identically across all data sources.

Every cursor adapter satisfies the DB-API 2.0 protocol contract:
- `execute(query: str, params: list[Any] | None = None) -> None`: Translates query and binds parameters to underlying client API.
- `fetchone() -> list[Any] | None`: Yields the next row tuple or `None`.
- `fetchall() -> list[list[Any]]`: Returns all remaining rows.
- `fetchmany(size: int) -> list[list[Any]]`: Returns up to `size` rows.
- `description: list[tuple[str, ...]] | None`: Metadata sequence yielding column names `[(col_name,), ...]`.
- `close() -> None`: Deterministically cleans up request resources.

#### Example: Vector Cursor Adapter Pattern (Qdrant / Pinecone)
```python
class _VectorCursorAdapter:
    """Adapts high-dimensional vector search/filter calls into a DB-API cursor."""

    def __init__(self, client: Any, collection_name: str) -> None:
        self.client = client
        self.collection_name = collection_name
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        # 1. Translate SQL WHERE / SELECT to Vector filter and projections
        # 2. Invoke client.scroll() or client.query()
        # 3. Populate self.description with projected field names
        # 4. Normalize JSON payloads into tabular row tuples
        ...

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        self._rows = []
```

### 3.3 Granular Schema Introspection Strategy (`query_builder/connectors/introspection.py`)

Every connector provides deterministic schema reverse-engineering adhering to the schema structure defined in `query_builder/schema.py`:
- `tables`: Map of table names to table metadata dictionaries containing `name`, `columns` list (`name`, `data_type`, `is_nullable`, `is_primary`, `comment`), `has_user_id`, `user_col`.
- `foreign_keys`: List of foreign key relationships (`table`, `column`, `target_table`, `target_column`).
- `relationships`: High-level relationship graph edges.
- `filter_sensitive`: Masking or exclusion of credential columns (`password`, `secret`, `token`, `hash`, `api_key`).

### 3.4 Synchronous & Asynchronous Execution Interfaces

Every missing connector will provide **dual-mode synchronous and asynchronous execution**:
1. **Synchronous Connector**: Subclasses `BaseConnector`, decorated with `@register_connector("name", aliases=[...], dialect=...)`. Implements `connect()`, `get_cursor()`, `introspect_schema()`.
2. **Asynchronous Connector**: Subclasses `AsyncBaseConnector`, registered as `async_<name>`. Implements `async def connect()`, `async def execute_raw()`, `async def introspect_schema()`.

---

## 4. Phased Implementation Roadmap & Prioritization (R3)

To ensure rapid value delivery, architectural stability, and adherence to 100% test coverage standards, the implementation of the 24 missing connectors is organized into **4 structured phases**:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Phase 1: Enterprise Relational & Modern Embedded SQL (6 Connectors)   │
│  Firebird, MonetDB, H2, Apache Derby, Sybase / SAP ASE, IBM Informix   │
│  Rationale: DB-API standard, deterministic catalogs, zero test flakiness│
└────────────────────────────────────┬───────────────────────────────────┘
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Phase 2: Observability, Cloud Log, Time-Series & Graph (6 Connectors) │
│  Azure Data Explorer (KQL), Prometheus, VictoriaMetrics, Timestream,   │
│  Memgraph, Amazon Neptune                                              │
│  Rationale: High observability demand, structured HTTP/Bolt APIs       │
└────────────────────────────────────┬───────────────────────────────────┘
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Phase 3: Real-Time Streaming SQL Gateways (3 Connectors)              │
│  ksqlDB, Apache Flink SQL, Apache Pulsar SQL                           │
│  Rationale: Completes streaming portfolio alongside Materialize & RW   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Phase 4: AI Vector Engines & Cloud NoSQL (9 Connectors)               │
│  Qdrant, Pinecone, Weaviate, Milvus, ChromaDB, LanceDB, Redis/Search,  │
│  Google Cloud Firestore, Google Cloud Bigtable                         │
│  Rationale: Complex cursor adaptation and AST-to-filter translation    │
└────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Enterprise Relational & Modern Embedded SQL (Priority Batch 1)
- **Engines**: Firebird, MonetDB, H2 Database, Apache Derby, Sybase / SAP ASE, IBM Informix
- **Files to Create**:
  - `query_builder/connectors/firebird.py` (`FirebirdConnector`, `AsyncFirebirdConnector`)
  - `query_builder/connectors/monetdb.py` (`MonetDBConnector`, `AsyncMonetDBConnector`)
  - `query_builder/connectors/h2.py` (`H2Connector`, `AsyncH2Connector`)
  - `query_builder/connectors/derby.py` (`DerbyConnector`, `AsyncDerbyConnector`)
  - `query_builder/connectors/sybase.py` (`SybaseConnector`, `AsyncSybaseConnector`)
  - `query_builder/connectors/informix.py` (`InformixConnector`, `AsyncInformixConnector`)
- **Dialect Extensions in `query_builder/dialects.py`**:
  - `FirebirdDialect`, `MonetDBDialect`, `H2Dialect`, `DerbyDialect`, `SybaseDialect`, `InformixDialect`
- **Introspection Extensions in `query_builder/connectors/introspection.py`**:
  - `introspect_firebird`, `introspect_monetdb`, `introspect_h2`, `introspect_derby`, `introspect_sybase`, `introspect_informix`

### Phase 2: Observability, Cloud Log, Time-Series & Graph (Priority Batch 2)
- **Engines**: Azure Data Explorer (ADX/KQL), Prometheus (PromQL), VictoriaMetrics (MetricsQL), AWS Timestream, Memgraph, Amazon Neptune
- **Files to Create**:
  - `query_builder/connectors/kusto.py` (`KustoConnector`, `AsyncKustoConnector`)
  - `query_builder/connectors/prometheus.py` (`PrometheusConnector`, `AsyncPrometheusConnector`)
  - `query_builder/connectors/victoriametrics.py` (`VictoriaMetricsConnector`, `AsyncVictoriaMetricsConnector`)
  - `query_builder/connectors/timestream.py` (`TimestreamConnector`, `AsyncTimestreamConnector`)
  - `query_builder/connectors/memgraph.py` (`MemgraphConnector`, `AsyncMemgraphConnector`)
  - `query_builder/connectors/neptune.py` (`NeptuneConnector`, `AsyncNeptuneConnector`)

### Phase 3: Real-Time Streaming SQL Gateways (Priority Batch 3)
- **Engines**: ksqlDB, Apache Flink SQL, Apache Pulsar SQL
- **Files to Create**:
  - `query_builder/connectors/ksqldb.py` (`KsqlDBConnector`, `AsyncKsqlDBConnector`)
  - `query_builder/connectors/flink.py` (`FlinkSQLConnector`, `AsyncFlinkSQLConnector`)
  - `query_builder/connectors/pulsar.py` (`PulsarSQLConnector`, `AsyncPulsarSQLConnector`)

### Phase 4: AI Vector Engines & Cloud NoSQL (Priority Batch 4)
- **Engines**: Qdrant, Pinecone, Weaviate, Milvus, ChromaDB, LanceDB, Redis / RediSearch, Google Cloud Firestore, Google Cloud Bigtable
- **Files to Create**:
  - `query_builder/connectors/qdrant.py` (`QdrantConnector`, `AsyncQdrantConnector`)
  - `query_builder/connectors/pinecone.py` (`PineconeConnector`, `AsyncPineconeConnector`)
  - `query_builder/connectors/weaviate.py` (`WeaviateConnector`, `AsyncWeaviateConnector`)
  - `query_builder/connectors/milvus.py` (`MilvusConnector`, `AsyncMilvusConnector`)
  - `query_builder/connectors/chroma.py` (`ChromaConnector`, `AsyncChromaConnector`)
  - `query_builder/connectors/lancedb.py` (`LanceDBConnector`, `AsyncLanceDBConnector`)
  - `query_builder/connectors/redis_search.py` (`RedisSearchConnector`, `AsyncRedisSearchConnector`)
  - `query_builder/connectors/firestore.py` (`FirestoreConnector`, `AsyncFirestoreConnector`)
  - `query_builder/connectors/bigtable.py` (`BigtableConnector`, `AsyncBigtableConnector`)

---

## 5. Testing & 100% Coverage Verification Strategy (R4)

To uphold Query-Builder's strict quality mandate, all newly implemented connectors must achieve **100% statement and 100% branch coverage** (`pytest --cov=query_builder --cov-branch --cov-report=term-missing`).

### 5.1 Deterministic Fake / Mock Driver Architecture
Zero tests may rely on external live network endpoints, cloud credentials, or background daemon processes. All drivers are tested using high-fidelity `unittest.mock` fixtures:
1. **Missing Driver Isolation**: Verify that `DriverNotInstalledError` is raised with the correct `pip install` remediation advice when the third-party client module is not installed.
2. **Connection Failure Resilience**: Verify that underlying socket/network exceptions during `connect()` are cleanly caught and wrapped in `ConnectionFailedError`.
3. **Cursor Adapter Protocol Validation**: Test `execute`, `fetchone`, `fetchall`, `fetchmany`, `description`, and `close` across success paths, parameter bindings, empty result sets, and malformed query responses.
4. **Schema Introspection Edge Cases**: Test table discovery, column metadata generation, primary key extraction, foreign key relationship mapping, and sensitive column filtering (`filter_sensitive=True`).
5. **Lifecycle Middleware Interception**: Verify that connectors pass compiled queries through `pre_compile`, `post_compile`, `pre_execute`, and `post_execute` interceptors without dropping query metadata.
6. **Dual Synchronous & Asynchronous Contracts**: Validate both `BaseConnector` (`with connector.get_cursor()`) and `AsyncBaseConnector` (`async with connector`, `await execute_raw()`).

### 5.2 Environmental & Resource Constraints Compliance
- **Sequential Execution**: Pytest and Vitest test suites must never run concurrently.
- **Vitest Concurrency Cap**: Headless React tests must be capped at 2 workers (`VITEST_MAX_WORKERS=2`).
- **Zero Remote Push Policy**: Code changes must remain local; unauthorized git pushes to remote remotes are prohibited.

---

## 6. Conclusion & Recommendation

Implementing the missing connectors in structured phases will expand Query-Builder's connectivity footprint from 65 to **89 engines**, transforming Query-Builder into the most universally compatible, secure, and extensible SQL and data querying platform in the Python and TypeScript open-source ecosystem.

Phase 1 (Enterprise Relational & Modern Embedded SQL) is recommended for immediate worker dispatch to establish instant commercial and legacy database coverage with zero risk of test flakiness, followed sequentially by Phases 2, 3, and 4.
