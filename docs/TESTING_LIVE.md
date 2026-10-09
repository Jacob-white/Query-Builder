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
  `certified` if this suite ran against a real engine through it, nothing failed, and every
  applicable *core check category* is covered (see [Tiers](#5-tiers)). Tiers measure testing
  depth, not just that something passed.

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
`tests/integration/.reports/latest.json`). Each engine also carries the evidence the tiers are
computed from:

```json
"family_kind": "sql",                       // or "native"
"core": ["connect", "introspect_tables", "..."],  // core categories that apply (async_parity only with an async class)
"categories": {
  "joins": {"passed": 4, "failed": 0, "xfailed": 0,
            "skipped": {"verified_limitation": 0, "declared_unverified": 0, "environment": 0}}
},
"limitations": {"verified": ["statement_timeout"], "declared_unverified": ["right_join"]}
```

Reports without `categories` (older runs) still load; they can never be `certified`
(they compute to `basic`).

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

### Check categories

Every result is attributed to ONE category (`tests/integration/categories.py`; a
`@pytest.mark.qb_category("name")` marker on the test, or `Case.category` for the declarative
query battery). Core categories per family:

| Family | Core categories |
| --- | --- |
| SQL (`Engine.family` set) | `connect`, `introspect_tables`, `introspect_columns`, `introspect_pk_fk`, `read_projection`, `filters` (eq/ne/range/in/like/null), `ordering`, `pagination`, `aggregates` (group/having/distinct), `joins`, `subquery_cte`, `parameter_safety` (injection-looking values stay data), `identifier_quoting` (reserved words, mixed case), `null_handling`, `write_refused` (validator, read-only session, DB-level read-only where supported), `error_mapping`, `statement_timeout`, `async_parity` (only with an async class) |
| NATIVE (document, key-value, search, graph, wide-column, vector, ...) | `connect`, `introspect`, `read_basic`, `read_filtered`, `ordering`, `pagination`, `value_safety` (quotes, unicode, regex/JSON-looking text round-trip as data), `write_refused` (several write forms), `error_mapping` (a bad native query surfaces as a `ConnectorError`/`QueryBuilderError`, never a raw driver exception), `async_parity` (only with an async class) |

Non-core categories (`window`, `secrets`, `spec_compile`, ...) are reported but never required.
Native engines declare their checks in `smoke.Smoke.checks` (`read_filtered`, `ordering`,
`pagination`, `value_safety`), `bad_queries`, `extra_seed` (the `qbit_special` object) and
`writes`. A category with neither checks nor a declared limitation is reported as UNTESTED.

### Limitations must prove themselves

When an engine legitimately lacks a feature (no statement timeout in SQLite, no `HAVING` in
QuestDB, no foreign keys in ClickHouse, ...) it is declared in that engine's `unsupported`
table (`tests/integration/engines.py`, or `Smoke.limitations` for native engines) and the
dependent test is **skipped with the reason**. A skip can hide a real gap, so a declaration
is a `Limitation(reason, probe=...)`:

```python
from tests.integration.engines import Engine, Limitation, register

unsupported={
    # statement probe: run through the NATIVE driver; the engine must raise
    "statement_timeout": Limitation("no server-side timeout", probe="SET statement_timeout = 1000"),
    # callable probe: (engine) -> bool, True when the feature WORKED (= the declaration is wrong)
    "case_sensitive_identifiers": Limitation("folds identifiers", probe=probe_case_sensitive_identifiers),
    # plain string: still accepted, but UNVERIFIED (no probe)
    "introspect_fk": "no foreign keys",
}
```

`test_limitations.py::test_declared_limitations_are_real` runs every probe live: if the engine
**accepts** the probed feature the declaration is wrong and the test fails, so the feature has
to be tested instead of skipped. Skips are then classified in the report:

| Class | Meaning |
| --- | --- |
| `verified_limitation` | the probe ran in this session and the engine rejected the feature |
| `declared_unverified` | a plain-string declaration (no probe), a probe that did not run, or an UNTESTED category; blocks `certified` when in a core category |
| `environment` | driver / service / credentials missing |

To add a probe: attempt the feature with the vendor driver (never the connector), keep it
side-effect free (create and drop your own `qbit_probe_*` objects), and return/raise so that
"the engine said no" is the outcome. Defects found and *reported but not fixed* are
`known_issues` strict xfails (see `smoke.py`, `RAW_ERROR_LEAKS` in `test_conformance.py`): they
flip to failures once fixed and block `certified` meanwhile.

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
| `certified` | a real engine ran the live suite **through that exact class** with **zero failures and no known issues**, AND every applicable core category of the engine's family has at least one pass (or a `verified_limitation` skip), AND no `declared_unverified` skip sits in a core category |
| `basic` | a real engine passed at least one live test with zero failures, but the certified bar is not met (shallow coverage such as smoke-only, unverified skips, or an old-format report without `categories`) |
| `emulated` | the same evidence against an emulator of the service; the evidence string states whether the depth bar was met |
| `verified` | no clean live run (or one with failures / known issues); unit tests in `tests/` exercise the class, and the registry matrix (below) passes for it |
| `experimental` | neither |

Order: `certified` > `basic` > `emulated` > `verified` > `experimental`. When several engines
exercise one class the best evidence wins (clean pass, real over emulator, depth bar met, more
covered core categories, more passes). `docs/CONNECTORS.md` shows per class the tier, pass /
skip counts, *core coverage* (e.g. `12/14 core categories`) and the `declared_unverified`
skips still to be probed. `query-builder verify-connectors` prints the same depth columns.

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

## Adding engines (families)

Engines live in per-family files so several people can add engines without editing the same
module:

- **Registry:** `tests/integration/engines_<family>.py`. It is imported automatically by
  `tests/integration/engines.py`; do `from tests.integration.engines import Engine, register` and
  call `register(Engine(...))`. Set `service` and `container_port` so the engine also works when
  the suite runs inside the compose network (`QB_IT_IN_DOCKER=1`, `scripts/it_docker_run.sh`).
- **Containers:** `docker/compose.<family>.yml`, project `qb-integration`, one compose *profile*
  named after the family, pinned image tags, healthchecks, host ports bound to `127.0.0.1` in the
  family's reserved range (below 49152; Windows reserves dynamic ranges above it), and named
  volumes only (removed by `down -v`).
- **Running:** always through `scripts/it_batch.py`. It takes a machine-wide lock and waits for
  enough free RAM, starts only the named services, runs only the named engines, tears down, and
  writes `tests/integration/.reports/<label>.json`:

  ```text
  python scripts/it_batch.py --label arango --engines arangodb \
      --compose docker/compose.nosql.yml --profile nosql --services arangodb
  ```

  Use `--linux` for engines whose Python driver cannot be installed on Windows, and
  `QB_IT_EXTRA_PIP="pkg1 pkg2"` to add drivers inside the Linux container.
- **Evidence:** record reports with `python scripts/gen_connector_status.py --record-live <reports...>`.
  Only classes that actually passed against a real engine become `certified`. An engine that
  merely speaks another engine's wire protocol is NOT evidence for a different class.
