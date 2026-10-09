# Live Engine Testing

The default `pytest` run exercises the connectors against mocks. This page is about
the opt-in suite that proves we can connect to, and correctly use, real engines:
`tests/integration/` (marker `integration`).

- **Opt-in.** `[tool.pytest.ini_options]` has `addopts = "-m 'not integration'"`, so the
  default run, CI and coverage never touch it. `pytest -m integration` runs it.
- **Never fails because a service is absent.** An unreachable engine or a missing driver
  skips the test with the exact reason (and the command that would fix it).
- **Real connector classes.** Data is seeded through each engine's *native* driver; every
  assertion goes through `query_builder` (compiler, validator, connector, introspection).
- **Honest status.** The result of a run feeds `docs/CONNECTORS.md`; a connector is only
  `certified` if this suite really ran against it and passed (see [Tiers](#tiers)).

## 1. Start the engines

Everything is in `docker/docker-compose.integration.yml` (compose project `qb-integration`,
pinned image tags, healthchecks, named volumes, ports bound to `127.0.0.1`). The ports are
deliberately non-default and high (`35432` for PostgreSQL, ...), so the stack cannot collide
with, or be mistaken for, a database you already run. Each is overridable with
`QB_IT_PORT_<ENGINE>` at `compose up` time.

```sh
# required tier: PostgreSQL, MySQL, MariaDB, ClickHouse (SQLite and DuckDB are in-process)
docker compose -p qb-integration -f docker/docker-compose.integration.yml up -d --wait
# extended tier: + SQL Server, CockroachDB, TimescaleDB, Trino, QuestDB, MongoDB,
#   Redis Stack, Elasticsearch, OpenSearch, Neo4j, Cassandra
docker compose -p qb-integration -f docker/docker-compose.integration.yml --profile extended up -d --wait

# always tear down with the named volumes
docker compose -p qb-integration -f docker/docker-compose.integration.yml --profile extended down -v
```

One-liners: `scripts/it_up.sh [extended]` / `scripts/it_down.sh`, or on Windows
`scripts\it_up.ps1 [-Extended]` / `scripts\it_down.ps1`.

> Windows reserves dynamic TCP port ranges (`netsh int ipv4 show excludedportrange
> protocol=tcp`). If a port in the table below is excluded on your machine, bind another:
> `QB_IT_PORT_MSSQL=36143 docker compose ... up`, and tell the tests with
> `QB_IT_MSSQL_PORT=36143`.

### Drivers

Install what you want to test; engines whose driver is missing are skipped.

```sh
pip install -e ".[dev]" 'psycopg[binary]' pymysql clickhouse-connect clickhouse-driver asynch \
  pymssql trino pymongo redis 'elasticsearch>=8,<9' opensearch-py neo4j cassandra-driver
```

`cassandra-driver` cannot load a default connection class on Windows without libev (Python
3.12+ also dropped `asyncore`), so test Cassandra from Linux: `scripts/it_docker_run.sh
cassandra` runs the suite inside a Python container attached to the compose network.

## 2. Run it

```sh
pytest -m integration                      # everything reachable
pytest -m integration -k postgres          # one engine
QB_IT_ENGINES=postgres,mysql pytest -m integration
pytest -m integration tests/integration/test_smoke.py     # non-SQL engines only
query-builder verify-connectors --live -e postgres -e mysql   # same, with a summary table
```

`-m integration` overrides the default `-m 'not integration'`; if your pytest setup
prepends other `addopts`, add `-o addopts=`.

### Configuration

Per engine, with defaults that match the compose file:
`QB_IT_<ENGINE>_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_DATABASE` (engine names are the
`ENGINES` keys in `tests/integration/engines.py`: `POSTGRES`, `MYSQL`, `MARIADB`,
`CLICKHOUSE`, `CLICKHOUSE_NATIVE`, `COCKROACH`, `TIMESCALE`, `MSSQL`, `TRINO`, `QUESTDB`,
`MONGODB`, `REDIS`, `ELASTICSEARCH`, `OPENSEARCH`, `NEO4J`, `CASSANDRA`). MySQL/MariaDB
also read `QB_IT_<ENGINE>_ROOT_PASSWORD` (used once to create the read-only login).

| Engine | Default endpoint | User / password |
| --- | --- | --- |
| postgres / timescale | `127.0.0.1:35432` / `:35433` | `qb` / `qb_it_password`, db `qb_it` |
| mysql / mariadb | `127.0.0.1:35306` / `:35307` | `qb` / `qb_it_password`, db `qb_it` |
| clickhouse (HTTP) / clickhouse_native | `127.0.0.1:38123` / `:39000` | `qb` / `qb_it_password`, db `qb_it` |
| cockroach | `127.0.0.1:35257` | `root`, insecure mode, db `qb_it` |
| mssql | `127.0.0.1:35143` | `sa` / `Qb_it_Passw0rd!`, db `qb_it` |
| trino | `127.0.0.1:38080` | user `qb`, catalog `memory` |
| questdb | `127.0.0.1:38812` (pg wire) | `admin` / `quest` |
| mongodb / redis | `:35017` / `:36379` | no authentication |
| elasticsearch / opensearch | `:39200` / `:39201` | security disabled |
| neo4j | `bolt://127.0.0.1:38687` | `neo4j` / `qb_it_password` |
| cassandra | `127.0.0.1:39042` | no authentication, keyspace `qb_it` |
| sqlite / duckdb | temp files under `$TMP/qb_integration` | n/a |

`QB_IT_STRICT=postgres,mysql` (or `all`) turns "unreachable" from a skip into a failure;
the CI workflow uses it for the required tier. `QB_IT_KEEP_DATA=1` keeps the seeded
`qbit_*` tables. All seeded objects are prefixed `qbit_`, so the suite does not touch your
own tables if you point it at a shared database.

### Report

Every run writes a JSON report (per engine: pass / fail / known-issue / skip counts, skip
reasons, engine version, platform) to `$QB_IT_REPORT` (default
`tests/integration/.reports/latest.json`).

## 3. What is checked

`test_conformance.py` runs one parametrized battery against every SQL engine:

| Area | Checks |
| --- | --- |
| Connectivity | `connect()` + `test_connection()` (status, dialect, engine version) |
| Introspection | seeded tables, columns, nullability, primary keys, foreign keys |
| Compile + execute | select/projection, every filter operator, AND/OR, IN subquery, inner/left/right joins, group/aggregate/having, order/limit/offset (+ total count), `DISTINCT`, CTE, window functions, `NULL` semantics, expected rows compared value by value |
| Parameter binding | injection-looking values (`'; DROP TABLE ...`, `' OR '1'='1`, `UNION`, backslashes, `%`, `_`) are data, and the data survives |
| Identifier quoting | reserved words (`select`, `group`, `order`), mixed case; non-ASCII identifiers are rejected |
| Read-only | writes via the raw path are rejected by the validator, by the read-only session check with the validator off, and (where the engine has read-only logins) by the database itself behind the validator |
| Statement timeout | a slow query is cancelled within the timeout and the connector stays usable |
| Secrets | wrong password: the error text, traceback chain and `repr/str(connector)` never contain it |

`test_smoke.py` runs the same style of battery for non-SQL engines (MongoDB, Redis,
Elasticsearch, OpenSearch, Neo4j, Cassandra): connect, introspect the seeded object, native
read, spec execution where the engine has a SQL compiler path, and write rejection.
`test_async_parity.py` runs every engine that has an async connector class through it and
compares introspection, reads and write rejection with the sync class on the same data.

When an engine legitimately lacks a feature (no statement timeout in SQLite, no `HAVING` in
QuestDB, no foreign keys in ClickHouse, ...) it is declared in that engine's `unsupported`
table in `tests/integration/engines.py` and the test is **skipped with the reason**, never
silently passed. Defects found and *reported but not fixed* are `known_issues` strict
xfails (see `smoke.py`): they flip to failures once fixed and block `certified` meanwhile.

## 4. Cloud engines

Managed engines cannot run in a container. `tests/integration/test_cloud_stubs.py` runs only
when the engine's variables are set; otherwise each test skips naming the variables.
Authentication that the vendor SDK already resolves from its own environment is not
duplicated.

| Engine | Required variables | Notes |
| --- | --- | --- |
| Snowflake | `QB_IT_SNOWFLAKE_ACCOUNT`, `_USER`, `_PASSWORD`, `_WAREHOUSE`, `_DATABASE` (opt. `_SCHEMA`) | `pip install snowflake-connector-python` |
| BigQuery | `QB_IT_BIGQUERY_DATASET` + `GOOGLE_APPLICATION_CREDENTIALS` | service-account JSON; `pip install google-cloud-bigquery` |
| Databricks | `QB_IT_DATABRICKS_HOST`, `_HTTP_PATH`, `_TOKEN` (opt. `_CATALOG`, `_SCHEMA`) | `pip install databricks-sql-connector` |
| Redshift | `QB_IT_REDSHIFT_HOST`, `_USER`, `_PASSWORD`, `_DATABASE` (opt. `_PORT`) | `pip install redshift-connector` |
| Athena | `QB_IT_ATHENA_S3_STAGING_DIR`, `_REGION` (opt. `_DATABASE`) | AWS credentials from the standard AWS environment or profile; `pip install pyathena` |
| Azure Synapse | `QB_IT_SYNAPSE_SERVER`, `_USER`, `_PASSWORD`, `_DATABASE` (opt. `_PORT`) | through the SQL Server connector; `pip install pymssql` |

```sh
export QB_IT_SNOWFLAKE_ACCOUNT=... QB_IT_SNOWFLAKE_USER=... QB_IT_SNOWFLAKE_PASSWORD=...
export QB_IT_SNOWFLAKE_WAREHOUSE=... QB_IT_SNOWFLAKE_DATABASE=...
pytest -m integration tests/integration/test_cloud_stubs.py -k snowflake -rs
```

The cloud stubs run `SELECT 1`, introspection, write rejection and secret scrubbing; they
create nothing. Use a least-privilege read-only role. They are stubs on purpose: a full
conformance dataset on a billed account is left to the owner of that account.

## 5. Tiers

`docs/CONNECTORS.md` lists every connector class once (aliases grouped) with a tier computed
by `query_builder/connectors/status.py` from evidence, not claims:

| Tier | Evidence required |
| --- | --- |
| `certified` | the live suite ran against a real engine **through that exact class**, with at least one pass, **no failures and no known issues**, in the latest recorded run (`docs/live_results.json`) |
| `verified` | no passing live run; unit tests in `tests/` exercise the class, and the registry matrix (below) passes for it |
| `experimental` | neither |

The registry-driven matrix (`tests/test_connector_matrix.py`, default suite, no services)
checks every registered class: importable, its documented install extra exists in
`pyproject.toml`, the third-party drivers it imports lazily are declared, instantiating
without the driver does not crash and `connect()` raises `DriverNotInstalledError`, its
`dialect_name` is a registered dialect, and sync/async parity is reported (JSON in
`$QB_MATRIX_REPORT`).

Record a run and regenerate the doc:

```sh
pytest -m integration                                   # writes tests/integration/.reports/latest.json
python scripts/gen_connector_status.py --record-live tests/integration/.reports/latest.json
# several reports (host + Linux container) are merged by engine:
python scripts/gen_connector_status.py --record-live host.json linux.json
python scripts/gen_connector_status.py --check          # CI-style: fail if CONNECTORS.md is stale
query-builder verify-connectors [--json]                # print the status table
```

`tests/test_connector_status.py` fails if `docs/CONNECTORS.md` is out of date.

## 6. CI

`.github/workflows/integration.yml` (Ubuntu only, `contents: read`) runs weekly, on demand
(`engines`, `extended` inputs) and on pull requests that touch `tests/integration/**`,
`query_builder/connectors/**` or `docker/**`. It starts the compose services, installs the
drivers, runs `pytest -m integration` with the required tier strict, and uploads the JSON and
Markdown report as an artifact. It is not part of the default PR gate otherwise.
