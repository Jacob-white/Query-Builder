# Changelog

## Unreleased

### Added
- **`QueryCompiler.compile_runnable()`** (and the public `inline_params` / `sql_literal`): the main query with its values
  written in as SQL literals, to show a person or download as a `.sql` file and paste into a SQL window. The bound form
  from `compile()` is still what executes. Placeholders inside quotes, comments and quoted identifiers are left alone,
  quotes in values are doubled, backslashes are doubled only for dialects that treat them as an escape, and a dialect with
  non-positional placeholders (or placeholders and values that do not line up) gives `None`. Verified by running the
  rendered SQL on SQLite and comparing its rows with the bound query's.
- **`QueryCompiler.compile_search(term)`**: keep only the rows where some output column contains `term`
  (case-insensitive) across *all* rows of the result, then page the matches with the spec's `limit` / `offset`. The text
  is a bound parameter with its LIKE wildcards escaped; the wrapper passes the AST validator. PostgreSQL family, SQLite,
  DuckDB, Redshift and the MySQL family.
- **`format_sql(sql)` and `QueryCompiler.compile_runnable(pretty=True)`**: lay the runnable statement out one clause per
  line with keywords in capitals, for a person to read or save as a `.sql` file. The layout is checked, not trusted: the
  formatter's output is used only when it equals the input apart from whitespace and the case of unquoted words (string
  values, quoted names and comments are compared exactly), and the input comes back unchanged otherwise or if the
  formatter fails. Off by default.
- **`check_columns(spec, schema)` and `SpecColumnError`** (`query_builder.spec_check`): refuse a spec that names a column
  which does not exist in a table of the query, before it compiles, with a message that names the column and the table,
  suggests the likeliest real column and lists the table's columns (also on `.column`, `.table`, `.suggestions`,
  `.available`). Covers the selected columns, filters and sort; leaves expressions, CASE columns, `*`, aliases,
  sub-queries and tables the schema does not list alone. Meant for callers that send the message back to a language
  model for a repair as well as for a person.
- **`audit_schema(schema)` / `SchemaAudit` (`query_builder.schema_audit`) and `query-builder schema --audit`**: list the
  gaps in what a schema tells a query builder or an AI helper: `..._id` columns named after a table (singular or plural)
  with no declared foreign key or relationship, id columns that name no table, and tables and columns with no description.
  Reads only names, links and descriptions. `--audit` exits 1 when a link is missing, so it can gate a build;
  `--known-not-link TABLE.COLUMN` and `--ignore-table-prefix PREFIX` keep a host's own conventions out of the report.
- **Unified Agent Tools & Model Context Protocol (MCP)**: Operator-pinned secure mode (`--lock-connection`), live schema catalog resources (`query-builder://schema/catalog`, `queryspec`, `semantic/metrics`), and tool calling support for `find_join_path`, `explain_and_advise`, and `execute_query`.
- **Autonomous Self-Healing Query Engine**: Automatic operator synonym mapping (`==` -> `eq`, `!=` -> `neq`, `like` -> `contains`), cross-table column resolution, table typo fuzzy matching, and iterative repair prompt generation.
- **Semantic Layer Grounding & `llms.txt`**: Metric and dimension expansion for NLQ translation, schema grounding, and standard `llms.txt` documentation manifest generator (`scripts/gen_llms_txt.py`).
- **Web Framework Integrations & TypeScript Client SDK**: Added `/explain`, `/join-path`, `/nlq`, and `/export/stream` endpoints to FastAPI and Django routers, schema TTL caching (`schema_cache_ttl`), and corresponding TypeScript client methods (`client.explain`, `client.findJoinPath`, `client.askAi`).
- **Python Fluent Query Builder & DX Guardrails**: `FluentQuery` / `query(table)` chainable query construction, `QuerySpec.builder()`, `QuerySpec.json_schema()`, unknown `QB_*` typo detection with warning suggestions, and PEP 562 lazy module imports.
- **Dialect-Level Column Masking Expressions**: Implemented `BaseDialect.format_masking_expression()` and query compiler projection support for `redact`, `hash`, `null`, `partial_email`, `partial_phone`, and `last4` data masking strategies.
- **Calculated Fields & Custom Expressions**: Added AST safety validation and compilation for client-supplied `expression` and `raw_expression` projected columns in `QueryCompiler._compile_dict_column()`.
- **Instance-Scoped & Thread-Safe Custom Operators**: Added optional `custom_operators` registry to `QueryCompiler.__init__` allowing query-compiler instances to safely evaluate local operators without mutating global state, and protected the global operator registry with re-entrant synchronization locks (`threading.RLock`).
- **Configurable Canonical Columns for Join Solving**: Added `canonical_columns` override support to `SchemaSnapshot`, `find_best_join_condition()`, and `find_join_path()` to allow schema-specific entity link keys while retaining standard fallback defaults.
- **Dialect Native Driver Limitation Probes**: Added native driver `Limitation` probes for CrateDB, StarRocks, Doris, TiDB, and OceanBase to test driver capabilities for introspecting foreign keys and case-sensitive identifier support.
- **`OrderBySpec.nulls` (`NULLS FIRST` / `NULLS LAST`)**: Added `nulls` support to `OrderBySpec`, `QueryCompiler._compile_order_by()`, `FluentQuery.order_by(..., nulls=...)`, and `SQLParser` (`ORDER BY ... NULLS FIRST | LAST` and window function `ORDER BY` clauses).
- **Complete `FluentQuery` Builder Surface**: Added `.metrics()`, `.rollup()`, `.cube()`, `.grouping_sets()`, `.with_cte()`, `.window()`, `.compile_runnable()`, `.compile_search()`, and `.check_columns()` to `FluentQuery`.
- **SQL Reverse Parser Enhancements (`SQLParser`)**: Added table alias resolution (`FROM users AS u`, `JOIN orders o ON ...`) across `SELECT`, `WHERE`, `JOIN`, `GROUP BY`, `HAVING`, and `ORDER BY`, plus `NOT LIKE` and `NOT ILIKE` operator parsing.
- **CLI & MCP Server Tooling**: Added `query-builder parse "<SQL>"` CLI subcommand, case-insensitive `query-builder schema --table` lookup, and `query_builder_parse_sql`, `query_builder_check_columns`, and `query_builder_audit_schema` MCP tools.
- **100% Strict Mypy Coverage Ratchet**: Added all remaining `query_builder` modules (`agent_tools`, `cli`, `egress_guard`, `mcp_server`, `runnable`, `schema_audit`, `server`, `server_security`, `spec_check`, `integrations.django`, `integrations.fastapi`, `nlq.self_healing`) to the strict mypy override list in `pyproject.toml` and enforced full-package coverage in `tests/test_typing_ratchet.py`.
- **React Visual Studio UI/UX Overhaul** (`@jacob-white/query-builder-react`, see `packages/react/CHANGELOG.md`):
  split-view docked workspace drawer (`<WorkspaceDock>`) keeping the visual canvas visible alongside live query results,
  live plain-English query summary bar (`<QuerySummaryBar>`) with interactive clause chips, 1-click FK join suggestions,
  inline column micro-actions (`<TableCard>`), compact progressive disclosure clause strips (`<TableJoinEditor>`,
  `<TableFiltersEditor>`, `<TableSortsEditor>`), and two-tier decluttered studio toolbar.
- **React helpers** (`@jacob-white/query-builder-react`, see `packages/react/CHANGELOG.md`): pure filter-kind, HAVING,
  join-proof, summary and SQL-file helpers extracted from a host application's Query Builder page; `completeJoins` /
  `loadCompleted` fill a loaded join's missing columns from the one declared link instead of letting it default to
  `id = id`, and `joinsSummary` now says the kind and columns of each join (bare `{table}` joins are listed as before).

### Fixed
- **Compiler Bind Parameter Ordering & `CASE WHEN` Count/Group-By Alignment**: Fixed `QueryCompiler.compile()` parameter ordering so `SELECT` bind parameters (`CASE WHEN`, `vector_search` `_distance`, `hybrid_search` `_score`) precede `FROM` derived-table and `WHERE` isolation (`tenant_id`, ownership `user_id`) parameters, excluded `SELECT`-only `CASE WHEN` parameters from `SELECT COUNT(*)` queries when no `GROUP BY` subquery wraps the projection, and duplicated `CASE WHEN` parameters when the `CASE WHEN` expression is repeated in `GROUP BY`.
- **Datasource & Dataclass Support in `check_columns()` and `audit_schema()`**: Fixed `spec_check.check_columns()` and `schema_audit.audit_schema()` to accept `SchemaSnapshot`, `TableMeta`, `ColumnMeta`, `TableSchema`, `ColumnSchema`, `QuerySpec`, and flat `from_sqlalchemy`/`from_prisma` schema dicts in addition to nested `{"tables": ...}` dicts.
- **Integer `0` Identity Handling (`user_id=0`, `tenant_id=0`)**: Fixed truthiness checks in `QueryCompiler._compile_base_isolation()`, `QueryCompiler._compile_join_isolation()`, and `execute_compiled_spec()` so integer `0` is treated as a valid identifier instead of skipped as falsy.
- **Derived Table `{"subquery": ..., "alias": ...}` Wrapper Support**: Updated `QueryCompiler._validate_table()` and `_compile_from()` to accept the `{"subquery": {...}, "alias": "..."}` derived-table shape declared in `QuerySpec.json_schema()`.
- **Custom Expression Aggregate Detection**: Expanded `QueryCompiler._compile_dict_column()` aggregate detection to recognize `STRING_AGG`, `ARRAY_AGG`, `GROUP_CONCAT`, `LISTAGG`, `STDDEV`, `VARIANCE`, `MEDIAN`, `PERCENTILE_CONT`, `PERCENTILE_DISC`, `BOOL_AND`, `BOOL_OR`, `ANY_VALUE`, `BIT_AND`, `BIT_OR`, and `BIT_XOR`.
- **Index Advisor Alias Resolution & Deduplication**: Updated `recommend_indexes()` in `query_builder/advisor.py` to resolve table aliases (`t1`, `t2`, custom aliases) back to real schema tables, inspect `schema_snapshot` primary keys, handle string `order_by` items and tuple filters, and deduplicate recommended indexes.
- **AST Complexity Scoring for Nested Clauses**: Updated `calculate_ast_complexity()` in `query_builder/security.py` to score derived-table subqueries, CTE subqueries, filter subqueries, and window functions.
- **Server, FastAPI, and Django Integration Hardening**: Fixed `SchemaSnapshot.to_dict()` serialization in FastAPI/Django/server routes, prevented in-place `SecurityPolicy` mutation across concurrent FastAPI requests, wired `nlq_service` into FastAPI `/nlq`, added `PermissionError`/`SecurityError` handling in Django NLQ views, resolved `tenant_id` for cache/telemetry in `server.py` secure mode, guarded `batch_size`/`chunk_size` parsing, unified CORS headers on streaming endpoints, and enforced a 10 MB request body cap in `parse_json_body()`.
- **React `loadSpec` / `specToState`**: join kinds in the compiler's form (`"INNER"`) are converted to the builder's form
  (`"INNER JOIN"`), so a loaded join is highlighted and compiles back with the same kind (a join loaded as `"inner"`
  used to compile as `LEFT JOIN`); a spec with no `activeTables` now activates its joined tables as well as its base
  table, so their column pickers are not blank. See `packages/react/CHANGELOG.md`.
- **`HavingSpec` and `OrderBySpec` Identifier & Key Parity**: Added `table_prefix`, `table`, `id`, and camelCase `tablePrefix` parity to `HavingSpec` and `OrderBySpec`, ensuring compiler validation accepts valid table qualifiers and prefixes across all clause specs.
- **`QuerySpec.json_schema()` Synchronization**: Fully synchronized `QuerySpec.json_schema()` with compiler capabilities, adding missing top-level keys (`vector_search`, `hybrid_search`, `ctes`, `window_functions`, `set_operations`, `rollup`, `cube`, `pivot`), column keys (`name`, `expression`, `format`, `case_when`, `masked`, `masking_strategy`, etc.), and all 41 built-in filter operators.
- **Analytical Dialect LIKE Escape Alignment**: Configured `like_escape_char = "\\"` on `BigQueryDialect`, `DatabricksDialect`, and `RedshiftDialect` ensuring consistent escaping behavior across warehouse query generation.
- **React Visual Compiler Dialect Alignment**: Aligned `packages/react/src/utils/compiler.ts` case-insensitive LIKE compilation for StarRocks, Doris, and Drill to emit standard `LOWER(...) LIKE LOWER(...)`.
- **Zero ESLint Warnings in React Package**: Cleaned up unused variables and stale memo dependencies across React visual query builder components and enforced `--max-warnings 0` in the lint script.
- **Table Alias Resolution in Data Masking & CLAC**: Resolved table aliases and multi-part schema-qualified column qualifiers across projected columns, calculated expressions, filters, `HAVING`, and `ORDER BY` clauses to eliminate side-channel data inference and ensure masking and Column-Level Access Control (CLAC) cannot be bypassed via aliasing.
- **Fail-Closed AST Safety & Tenant Isolation on Raw SQL**: Enforced AST safety validation (`validate_sql_ast()`) and rejected raw SQL execution under active tenant isolation across HTTP server endpoints (`/api/v1/execute`, `/api/v1/stream`, `/api/v1/export/stream`), connection pool (`ConnectionPoolManager.execute_query()`), and Django views (`execute_view`, `export_view`, `export_stream_view`, DRF views).
- **DNS Pinning for Async Connectors**: Added connect-time DNS resolution pinning in `AsyncBaseConnector` to eliminate time-of-check to time-of-use DNS rebinding risks.
- **Recursive Row-Level Security Policy Application**: Enhanced `apply_security_policy()` to enforce row-level filters and table permissions recursively across CTEs, set operations, derived tables, and subquery filters.
- **Compiler Sub-Compile Parameter Counter**: Fixed parameter placeholder counter sharing in `QueryCompiler._sub_compile()` to prevent placeholder collisions across subqueries and CTEs.
- **Semantic Model Schema & Dataclass Synchronization**: Supported camelCase key normalization in `SemanticModel.from_dict()` and synchronized `QuerySpec` dataclasses and `QuerySpec.json_schema()` with all compiler capabilities.
- **NLQ Semantic Metric Ordering & `COUNT_DISTINCT`**: Reordered `NlqService.translate()` to expand semantic metrics before AST validation and supported `COUNT_DISTINCT` across `NlqAstValidator`, client SDK, and React visual compiler.
- **Connection Pool Lifespan Tracking**: Preserved original connection creation timestamp in `ConnectionPool` and `AsyncConnectionPool` across acquire/release cycles to ensure proper eviction after `max_lifespan_seconds`.
- **Async Pool Lock Concurrency**: Refactored `AsyncConnectionPool` using `asyncio.Condition`, moving connection establishment, health checks, and teardown outside pool locks to eliminate busy-waiting polling loops.
- **SQLParser HAVING & Window Function Duplication**: Added `HAVING` clause parsing to `SQLParser` and eliminated duplicate base column emission for window functions.
- **Advisor Index Prefix Stripping**: Fixed `recommend_indexes()` in `query_builder/advisor.py` to strip table qualifiers from column names when generating index names and DDL statements.
- **Sorting by a count or total** (`order_by` naming an aggregate's label) now compiles to `ORDER BY "label"`. It
  compiled to `ORDER BY "t1"."label"` before, a column that does not exist, so the query passed validation and failed in
  the database.
- **Sorting by the alias of an ordinary column** (`order_by` with no table prefix naming a selected column's `alias`)
  now compiles to `ORDER BY "alias"` too; it compiled to `ORDER BY "t1"."alias"` before, a column that does not exist,
  so the query passed validation and failed in the database. Nothing that worked changes: a table prefix still means
  that table's column, and an unprefixed name that is a column of the base table keeps meaning that column even when an
  alias has the same name. Verified by running the queries on SQLite.
- **`query-builder mcp` CLI dispatch**: Fixed zero-argument `McpServer()` instantiation when no CLI flags are supplied, preventing `TypeError` on custom or default server classes.
- **CamelCase parameter support in QuerySpec**: Added `InitVar` aliases (`tablePrefix`, `leftTable`, `leftCol`, `rightCol`) to `FilterSpec`, `OrderBySpec`, and `JoinSpec` to accept payloads directly from NLQ and TypeScript client serializers.
- **Django and FastAPI Router Parity**: Implemented `/explain/`, `/join-path/`, `/nlq/`, and `/export/stream/` views in `create_django_urls` and `create_drf_views` for full parity with FastAPI.
- **Async Connector Execution in Agent Tools**: Fixed `execute_query` in `agent_tools.py` to safely await coroutines from `AsyncBaseConnector` instances.
- **Semantic Layer Expression Expansion**: Extended `expand_metrics_and_dimensions` to expand dimensions in `filters` and `order_by`, and metric calculations in `having`.
- **Self-Healing Query Engine Enhancements**: Added support for additional operator synonyms (`starts with`, `ends with`, `is not`, `isnull`, `isnotnull`), join synthesis for tables referenced in `having` and window clauses, and typo healing for table prefixes.

### Breaking
- **`query-builder serve` now starts in secure mode.** The server, not the client, chooses the tenant,
  the policy and the connection; it refuses a client-supplied `tenant_id` / `policy` / `config`, raw SQL
  and every endpoint outside a small allow-list, fails closed (401) when no tenant resolves, applies the
  `production` security profile, and sends no wildcard CORS header. A bare `serve` registers no database
  (pass `--connections FILE`) and says so at start-up. To keep the old open behaviour for local
  development pass **`--insecure`** (it prints the security notice, and refuses the secure-only
  `--connections` / `--allow-origin`). `--secure` is still accepted and does nothing extra. The library
  function `create_server()` is unchanged: without `security=` it still trusts the request, as documented
  in `docs/SECURE_DEPLOYMENT.md`.
- **Python 3.11+ required** (was declared 3.9+, but the package already imports `typing.Self`
  and uses runtime `X | Y` unions, so 3.9/3.10 never worked). Classifiers, README badge, ruff
  target and `query-builder doctor` now agree.
- **Node 22.22.2+ required** for the React package's toolchain (`jsdom@30` / `undici@8`).
- **React public types tightened** where `any` was removed; see `packages/react/CHANGELOG.md`.
- `RedisQueryCache(socket_timeout=...)` (never released) is now `connect_timeout` / `command_timeout`.
- **Database errors from `execute()` / `execute_raw()` are now `QueryExecutionError`** (a
  `ConnectorError`) instead of the raw vendor exception. Backward compatible by design: the raised
  object is *also* an instance of the original driver class (e.g. `sqlite3.OperationalError`,
  `psycopg.Error`), so existing `except <driver error>` handlers keep working, and the original
  is kept as `__cause__`. Falls back to a plain `QueryExecutionError` if the driver class cannot
  be combined. `SecurityError`, `CompilationError`, `ValueError`, `TimeoutError` and middleware
  errors still pass through unchanged. Code that checks `type(exc) is ...` is affected.

### Packaging (breaking for install commands)
- Optional extras rebuilt (`pyproject.toml`): `mysql` now installs pure-Python `pymysql` (the C
  driver is `mysql-native`); `h2`/`derby` install `JayDeBeApi` (what those connectors import);
  `pinecone` installs `pinecone` (not the deprecated `pinecone-client`); `prestodb` installs
  `presto-python-client`; `greptimedb` installs `psycopg`. Alias extras (`postgres`, `neon`,
  `supabase`, `mongodb`, `kusto`, ...) now reference their canonical extra instead of copying it.
- `all` now installs only drivers that are pure Python or ship wheels everywhere; the former
  hand-copied list (including `mysqlclient`, `pymssql`, `pyodbc`, `ibm-db`, ...) is `all-native`.
  New family extras: `sql`, `cloud-warehouses`, `nosql`, `vector`, `streaming`; new `server`
  (FastAPI/Starlette/Uvicorn/httpx) and `django` extras.
- The package version is single-sourced from `query_builder.__version__`; `py.typed` is shipped;
  new console script `query-builder-mcp`; PyPI classifier is now `Development Status :: 4 - Beta`;
  sdist includes tests, docs and changelog.
- React package: `dist/` now contains only the Vite bundles plus declarations (`tsc` no longer
  writes stray `.js` next to them; stale files cannot ship), `"type": "module"`,
  `"sideEffects": false`, ESM `.d.ts` + CJS `.d.cts` declarations per export condition, `react`
  is a required peer dependency, the tarball no longer includes `src/`.

### Security
- **CSV exports no longer let a cell run as a spreadsheet formula** (behaviour change, on by default).
  `export_dataset`, `stream_export_dataset` and `CsvStreamExporter` now write text that starts with `=`, `+`, `-`,
  `@`, a tab or a carriage return, in a cell or in the header, with an apostrophe in front, because Excel and
  LibreOffice run such a cell as a formula when the file is opened and a query can return text someone else
  typed (or a column alias a caller chose). Numbers, booleans and `None` are untouched, so a negative number stays
  a number. Pass `neutralize_formulas=False` to get the text exactly as it was (for a consumer that is not a
  spreadsheet); `csv_safe_cell(value)` is the same rule as a function. The `.xlsx` writer stores text as inline
  strings, which Excel never evaluates, and is unchanged. The React package's CSV download got the same fix
  (see `packages/react/CHANGELOG.md`).
- Tenant and row-level-security predicates are now enforced **outside** the client's filter
  group (`WHERE tenant = ? AND (client filters)`), so a client `OR` can no longer widen them.
  Client-supplied `_enforced` flags are stripped; unbalanced client parentheses cannot close
  the wrapping group.
- SQL validator (`validate_sql_ast`): single-pass lexer replaces regex comment/literal
  stripping and is evaluated under every plausible dialect interpretation (backslash escapes,
  `#` comments, dollar quoting, bracket identifiers); relation detection is token based
  (`TABLE x`, `STRAIGHT_JOIN`, comma lists); functions that execute SQL or read files are denied;
  catastrophic-backtracking patterns removed (inputs that took minutes now take milliseconds).
- Per-filter `combiner` values are whitelisted to `AND`/`OR` in the TypeScript compiler and
  parser as well as the Python compiler.

### Security (HTTP server tenant isolation, explicit security configuration)
- **Opt-in secure mode for the HTTP server** (`query-builder serve --secure`, `create_server(security=ServerSecurity(...))`,
  new `query_builder/server_security.py`). By default the server trusts the request: connection settings (`config`),
  `tenant_id` and `policy` come from the body, there is no authentication, and isolation applies only when a request
  carries a tenant - verified on real data: a request with no `tenant_id` returned every tenant's rows even with
  `QB_ENFORCE_TENANT_ISOLATION=true`. Secure mode enforces, in one place before any handler runs: a small endpoint
  allow-list (compile, validate, execute, explain, health, docs); no client-supplied `tenant_id` / `policy` / `config`
  (refused with 403, not ignored); no raw SQL; the tenant from the operator's resolver (401 when none resolves, a
  crashing resolver also fails closed); the spec rewritten once with the resolved tenant and a server-side policy;
  the operator's connection only; no wildcard CORS. New flags: `--secure`, `--tenant-header`, `--connections`,
  `--default-connection`, `--allow-origin`. Default behaviour is unchanged. 76 tests; the checker was mutation-tested
  (19 deliberate breakages, all caught).
- **Fixed: the tenant was silently ignored on some paths.** With a `tenant_id` in the request, `execute` on a registered
  `connection_id` (the pooled path), `/api/v1/export` and `/api/v1/export/stream` returned the other tenant's rows. The
  tenant policy is now applied on every endpoint that returns rows (one shared helper). Raw SQL is still never rewritten.
- **Changed (security): an explicit security configuration is honoured by connectors.** The permissive "nothing
  configured" defaults (private networks allowed, TLS not enforced) used to apply even when the application had chosen a
  policy: `serve --profile production`, `configure_query_builder(profile=...)` and `configure_security(...)` left
  connectors permissive; only the `QB_SECURITY_PROFILE` variable and a per-connector `security=` were honoured. They now
  are (`security_explicitly_configured()`; `reset_security_config()` clears it). **Behaviour change:** an application that
  configured a strict profile in code and connects to private addresses will now be refused, as it asked to be; allow
  them explicitly (`allow_private_networks=True` with `allowed_hostnames`). The full test suite needed no changes.
- **Start-up security notice** for `serve` and `mcp` (stderr): no authentication, where the connection settings and tenant
  come from, and whether the network policy is permissive. `--no-security-notice` silences it. `mcp` gains `--profile`.

### Security (database-side read-only session: Vertica)
- The Vertica connector now sets `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` on every
  connection when `enforce_read_only_session` is on (the default), and declares
  `read_only_support = "enforced"`. Probed and tested on a real Vertica 9.2: INSERT, UPDATE, DELETE,
  TRUNCATE, DROP and CREATE are refused by the engine, SELECT works, a COMMIT does not lift it, and the
  same statements succeed with enforcement off (control). A `SUPER`-class role can still change session
  settings, so a read-only database role remains the strongest guarantee.

### Security (SQL validator: more functions denied)
- Probing the validator with dialect-specific queries found functions it still accepted that read server
  files, reach other systems or change state from inside a `SELECT`. Now rejected: DuckDB `glob`, `getenv`,
  `duckdb_secrets`, `which_secret`, `sqlite_scan` / `postgres_scan` / `mysql_scan` / `iceberg_scan` /
  `delta_scan`, `st_read*`, `read_xlsx`; ClickHouse `mongodb`, `redis`, `gcs`, `azureBlobStorage`,
  `deltaLake`, `iceberg`, `hudi`, `sqlite`, `urlCluster`, `fileCluster`, `clusterAllReplicas`; BigQuery
  `EXTERNAL_QUERY`; SQL Server `fn_xe_file_target_read_file`, `fn_get_audit_file`, `fn_trace_gettable`;
  PostgreSQL `nextval`, `setval`, `pg_notify`, `pg_advisory_*`, `pg_logical_*`, `pg_backup_*`,
  `pg_switch_wal`; MySQL `GET_LOCK`, `RELEASE_LOCK`. A column or alias that shares a name still works.
  Not changed (documented): resource-exhaustion functions (`zeroblob`, `generate_series`), which need
  the database's own limits and timeouts, and catalog views, which are governed by the restricted-table list.

### Security (CodeQL py/stack-trace-exposure, alerts 94-96)
- The Django views answered `401` with `str(exc)` for any `PermissionError`, including the OS's own
  (`[Errno 13] Permission denied: '<path>'` from a driver opening an unreadable file), which put a server
  path in the response. Tenant-resolution refusals now use a dedicated `TenantResolutionError`
  (a `PermissionError` subclass, so existing handlers still catch it) and keep their wording; any other
  `PermissionError` gets `"Unauthorized."` with the same `401`.

### Security (CodeQL py/stack-trace-exposure, alert 93)
- A disabled-feature refusal reaches API clients as text built from the engine's own feature names, not from the
  exception's string. `DisabledFeatureError` is raised in one place with a fixed template, so no stack trace or internal
  detail could reach a client today (and the wording clients see is unchanged); this makes it structurally true: the new
  `capabilities.disabled_feature_message()` accepts a feature name only if the engine defines it (or the integrator listed
  it in `custom_overrides`), so a future raise site that passes dynamic text or a custom `message` cannot expose it. Used
  by the FastAPI, Django, DRF and Ninja integrations at all seven places that previously returned `str(exc)`.

### Security (connect-time egress guard, found by auditing what happens after validation)
- **DNS rebinding and redirects were not covered after validation.** Under a strict profile the Redis
  connector passed validation against a public IP, then its driver re-resolved the name and connected to
  `169.254.169.254`; only PostgreSQL pinned the validated address. A 302 to an internal address was followed
  by the Prometheus/VictoriaMetrics adapter (`requests`), Cloudflare D1 (`requests`, with the SQL body) and
  the InfluxDB version probe (`urllib`). New `query_builder.egress_guard` checks the real destination IP of
  every `socket.connect` a connector makes inside `connect` / `execute` / `execute_raw` /
  `introspect_schema` / `test_connection` (sync and async, per thread and asyncio task, Windows proactor
  loop included) against the same policy. A name passed to `connect` is resolved once and connected by the
  checked address. On by default; `network.connect_time_guard = False` disables it. It cannot see drivers
  that connect in C without Python's `socket` (libpq, mysqlclient, ibm_db, ODBC), `uvloop`, or threads a
  driver starts itself - see SECURITY.md and docs/THREAT_MODEL.md for the limits and the network-level
  controls that cover them.
- The Prometheus/VictoriaMetrics requests adapter and Cloudflare D1 no longer follow redirects (a 3xx is
  reported); the InfluxDB version probe follows none and speaks only `http(s)` (`urlopen` also accepted
  `file:` and `ftp:`).
- **Documented the permissive default network policy** (SECURITY.md 3.2 and section 5, THREAT_MODEL.md 3.6 and 4,
  README, quickstart, API reference): a connector created without `security=` while `QB_SECURITY_PROFILE` is
  unset allows private/internal addresses and does not enforce TLS, so `serve`, `mcp` and the CLI - which pass no
  `security=` - only block the credential endpoints by default. Deployments that accept connection settings from
  users or agents must set a `production`/`strict` profile and add network-level egress controls. The
  `QB_ALLOW_PRIVATE_NETWORKS` / `QB_ENFORCE_TLS` table rows previously claimed the opposite defaults.
- The always-forbidden credential endpoints now also include AWS ECS/Fargate (`169.254.170.2`) and EKS Pod
  Identity (`169.254.170.23`, `fd00:ec2::23`), Azure WireServer (`168.63.129.16`), Alibaba Cloud
  (`100.100.100.200`) and the legacy Oracle Cloud endpoint (`192.0.0.192`); they were reachable under the
  default policy.

### Security (key=value DSN egress check)
- **Key=value DSNs bypassed the network-egress check**: `validate_network_target` read a Db2/ODBC
  style `DATABASE=x;HOSTNAME=169.254.169.254;PORT=50000;` string as a single hostname, so the
  cloud-metadata address was **allowed** under the default policy. `HOSTNAME`/`HOST`/`SERVER`/
  `ADDRESS`/`Data Source` and `PORT` are now extracted and validated.

- **The network-egress check missed most connection-string shapes** (found by probing all 138
  connectors with the cloud-metadata address): 26 of 37 formats let it through under the default
  policy - libpq `host=... port=...`, JDBC URLs, Oracle `//host` and TNS descriptors, comma host
  lists, `user:pw@host`, `host:port` or a URL inside `host`, multi-host URLs, and the keys `hosts`,
  `servers`, `nodes`, `connstr`, `gateway_url`, `base_url`, `supabase_url`, `bootstrap_servers`,
  `conninfo`, `jdbc_url`, ... One shared parser (`extract_address_targets`) now reads every
  address-like config key **and** the address attributes a connector keeps outside its config
  (`collect_target_config`, used by the sync and async bases). Multi-host URLs (replica sets) were
  previously rejected with a port error and are now validated host by host. Strict TLS profiles
  now also reject `http://` under the newly checked keys (e.g. `base_url`), as they already did for
  `url`. Addresses the first pass already validates are not resolved a second time.

### Security (structural validation, DB-side enforcement, SSRF pinning)
- New sqlglot **structural layer** (`query_builder/sql_ast.py`): `validate_sql_ast(..., dialect=None)`
  now requires BOTH the legacy lexer layer and an AST allowlist (one statement, read-only query
  root, no DML/DDL/Command/INTO/locking nodes, no denied function, no restricted real relation,
  scoped CTE resolution) to accept the query; fails closed when sqlglot cannot parse. Results gain
  `violation_layers`; structural messages are prefixed `[sqlglot-ast]`. `sqlglot` is a new dependency.
- Found by the new differential fuzzers (SQLite / PostgreSQL / DuckDB oracles): an unterminated
  `/*` was treated as a syntax error (SQLite accepts it as a comment), letting
  `SELECT $$ FROM auth_user/* $$` slip through; `pragma_*` table functions are now denied.
- Connectors call a new `apply_read_only(connection)` hook from `connect()`: real read-only sessions
  for SQLite (`query_only` + `mode=ro`), DuckDB (`read_only=True` for files), PostgreSQL family,
  MySQL/MariaDB/TiDB and ClickHouse; documented `none` for engines without a mechanism.
- SSRF: one injectable resolver, every resolved address validated (embedded IPv4 in NAT64/6to4/
  Teredo/mapped/compat), trailing-dot / ideographic-dot metadata hostnames, and
  `resolve_and_validate_target` + libpq `hostaddr` pinning for the PostgreSQL family.
- `docs/THREAT_MODEL.md` documents guarantees, non-guarantees and how to run the fuzz suites.

### Fixed (defects found by running the live suite against real engines)
- **Bigtable:** `connect()` passed `app_profile_id` to `Client.instance()`, which has no such
  parameter, so every real connection failed; the profile is now bound per table. Compiled specs also
  read `cf.name` as table `cf`, column `name` (every value came back NULL); the dialect now keeps the
  `family.qualifier` as one column (`BaseDialect.dotted_column_names`) and emits no table alias.
- **DataFusion:** SQL/planning errors surfaced as a raw `ValueError`; they now map to
  `QueryExecutionError`.
- **Live suite:** newly run against real engines: DataFusion, Polars, LanceDB, fakesnow, generic
  SQLite/DuckDB, Spanner, Drill, Milvus, YugabyteDB, Firestore, Bigtable, Cosmos DB. Fixed three
  broken compose definitions (Drill healthcheck used absent `curl`; Milvus lacked its embedded-etcd
  config; Yugabyte bound YSQL to loopback; Bigtable/Cosmos healthchecks used `/dev/tcp` under `sh`).
  Engine traits are declared as probe-verified limitations (Drill returns NULL for unknown columns;
  the Yugabyte test container uses trust auth).
- **MongoDB (pymongosql):** compiled specs silently returned no rows because the driver cannot
  resolve `alias.column` references or double-quoted identifiers (and keeps quotes in result column
  names). The MongoDB dialect now emits bare identifiers, bare aliases and an un-aliased `FROM`
  (new `BaseDialect.supports_table_aliases` knob); joins raise a clear `CompilationError`. The live
  known-issue is gone and `MongoDBAtlasSQLConnector` is re-recorded as certified.
- **Async connectors silently reported an empty schema.** Seven async classes (Exasol,
  GreptimeDB, Materialize, PrestoDB, RisingWave, Spark SQL, StarRocks) inherited a default
  `introspect_schema` that returns "no tables"; they now introspect for real, and a test fails if
  any registered async connector inherits the empty default again.
- **CrateDB:** the dialect emitted `%s` placeholders to a driver that binds `?` (every bound query
  failed); primary keys are read from the catalog instead of guessing a column named `id`;
  `LIKE` escapes `%`/`_`; a parameter inside a `WITH` clause was bound out of order and silently
  returned wrong rows (the compiler now orders CTE parameters the way CrateDB numbers them).
- **Pinecone:** `OFFSET` was silently dropped; metadata columns were missing from introspection
  (`list()` yields id lists, not page objects); an index on Pinecone Local used `https`; async
  introspection crashed on `IndexList`; results are now sorted nearest-first.
- **Materialize, RisingWave, TDengine:** bound `LIMIT`/`OFFSET` are rejected by the engine, so the
  values are inlined (int-coerced). **StarRocks:** `ILIKE` emulation, `LIKE` escaping, primary keys
  via `column_key`. **GreptimeDB:** schema name inlined (the server cannot type a bound parameter).
  **TiDB:** `SET SESSION TRANSACTION READ ONLY` is a no-op there, so read-only is a documented
  "not enforced by the engine" mode (`docs/THREAT_MODEL.md`). **Trino:** a real statement timeout.
- Driver exceptions from `execute()` are `QueryExecutionError`; the compatibility subclass also
  keeps vendor `__str__` working (it broke `clickhouse_driver`) and falls back safely.
- SQL literal scanner: linear time (CodeQL `py/polynomial-redos`) and dialect-aware backslash
  handling (T-SQL `''`).
- `scripts/it_batch.py` teardown now removes services that sit behind a compose profile.
- **RisingWave `SELECT DISTINCT ... ORDER BY`** was rejected ("ORDER BY expressions must appear
  in select list") because the compiler ordered by `"t1"."col"` while the select item is
  `"t1"."col" AS "col"`. New dialect knob `distinct_order_by_alias`: RisingWave orders by the
  select alias. Other dialects' SQL is unchanged.
- **RisingWave aggregate window without ORDER BY** (`SUM(x) OVER (PARTITION BY k)`) silently
  dropped every row whose partition key is NULL (engine v2.1.2). New dialect knob
  `window_partition_null_rows_dropped`: for `SUM/AVG/COUNT/MIN/MAX` with `PARTITION BY` and no
  ORDER BY/frame, RisingWave gets the equivalent `ORDER BY <first partition key> ROWS BETWEEN
  UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`, which it evaluates correctly. Other dialects
  are unchanged. Both live cases now pass (RisingWave 18/18 core categories).
- **MongoDB (pymongosql) `''` quote escape**: pymongosql ignores the doubled-quote escape and
  silently returned no rows for `WHERE name = 'O''Brien'`. `execute_raw` / `execute(sql=...)` on
  the MongoDB connector now rewrites such literals into bound `?` parameters (which pymongosql
  handles correctly), via the new `BaseConnector.prepare_raw_sql` hook (identity by default;
  runs after the safety checks). The strict-xfail known issue for it is removed. The separate
  known issue (pymongosql rejecting compiler table aliases / double-quoted identifiers) remains.

- **Presto, Vertica, Db2, Informix (first live runs)**:

  - Presto: `LIMIT ?`/`OFFSET ?` cannot be bound and `OFFSET 0` is rejected, so values are inlined

    and a zero offset is omitted; `test_connection` no longer calls the missing `version()`.

  - Vertica: introspection reads `v_catalog` (there is no `information_schema`); `ILIKE` declares

    an `ESCAPE` so a literal `%`/`_` is not a wildcard.

  - Db2: primary keys no longer include foreign-key columns, FK column lists are split and trimmed,

    `AVG` is cast to `DOUBLE` (it was integer division), LIKE declares `ESCAPE`, and the statement

    timeout now works (it must be set on the prepared statement).

  - Informix: `?` placeholders (not `%s`), `DELIMIDENT=y` added to the DSN so quoted identifiers

    work, real PK/FK columns from `sysindexes`, `SKIP`/`FIRST` inlined (bound markers were

    mis-ordered around a CTE), typed `HAVING` markers, LIKE `ESCAPE`, a statement timeout, and the

    validator now reads `SELECT SKIP n FIRST m DISTINCT`.



- **chDB, H2, Derby (first live runs)**:
  - H2/Derby over JayDeBeApi returned the underlying column name instead of the `AS` alias
    (`name` for `t2.name AS dept`); the cursor now reports JDBC column labels.
  - Derby: the connection test and introspection sent a trailing `;` (a syntax error), `AVG` over an
    INTEGER was integer division (now cast to `DOUBLE`), and foreign keys are read through
    `DatabaseMetaData.getImportedKeys` because Derby's SQL catalog has no key column names.
    Derby has no `WITH` (CTE) support; both that and its upper-case folding of unquoted names are
    declared limitations backed by probes.

- **Doris (first live run)**: the dialect emitted `ILIKE`, which Doris does not have, so every
  substring filter (`contains`, `starts_with`, `ilike`, ...) failed with a parse error; it now uses
  `LOWER(x) LIKE LOWER(?)` with the MySQL `\` escape, like StarRocks. Doris column names must be
  ASCII, declared as a limitation with a probe (the harness uses an ASCII stand-in column).

- **OceanBase (first live run)**: foreign-key introspection returned nothing because the connector
  used the ANSI query (it needs `constraint_column_usage`, which MySQL mode lacks) and swallowed the
  error; it now uses the MySQL-style query. The test container's healthcheck called the `mysql`
  client, which the image does not ship (it has `obclient`), so it could never become healthy.

### Changed
- `compiler.py`, `cli.py`, `server.py` and `dialects.py` were restructured without behaviour
  change (golden snapshots written before the refactor pin SQL, CLI output, HTTP responses and
  every dialect's output). `query_builder.dialects` is now a package; all names still import from
  `query_builder.dialects`.
- Live certification: connector tiers are computed from evidence (see `docs/CONNECTORS.md`);
  limitations that are claimed must be probe-verified against the real engine.

### Fixed
- Mixed `AND`/`OR` filters round-trip correctly between SQL, the React client spec and the
  Python compiler (every filter carries a combiner once any is `OR`); Python
  `parse_sql_to_spec`, `FilterSpec` and the NLQ validator preserve combiners.
- `useStreamingQuery` no longer aborts its own request; terminal events fire exactly once.
- `RedisQueryCache`: `connected` reflects a real ping (cached for 5 s), failed reads back off
  without blocking invalidation, `clear()` scans and deletes in bounded batches.
- `useQueryBuilder({ initialSpec })` now converts spec-shaped input like `loadSpec` does.
- Raw-SQL "your SQL was replaced" notice only appears when information would actually be lost.
- Starter app: per-request SQLite connections; thread-bound shared connection removed.

### Tooling
- mypy ratchet: `compiler`, `parser`, `sql_ast`, `ast_validator`, `server`, `cli` and the
  `dialects` package are now strictly type-checked (only `connectors` and `integrations` remain
  in the baseline). Type fixes are annotation-only; no behavior change.
- Release workflow (`.github/workflows/release.yml`): tag-triggered, dry-run by default, PyPI trusted
  publishing, npm `--provenance`, SBOMs and checksums; see `docs/RELEASING.md`.
- CI: `pip-audit`, `pnpm audit`, dependency review, CycloneDX SBOMs, package build/`twine check`,
  `publint`/`attw`; Dependabot; actions pinned to commit SHAs. Added `CONTRIBUTING.md` and a PR template.
- CI (`.github/workflows/ci.yml`): Python 3.11-3.13 on Linux and Windows, React on Node 22/24;
  coverage floors (Python 99%, React 99/96/99/99); ruff `B`, `I`, `UP`, `S` and format check;
  ESLint `no-explicit-any` as an error and a warning ratchet.
- Test environment fixes: `localStorage` shim for newer Node, path-independent TypeScript
  tests, driver isolation for H2/YugabyteDB tests, optional-dependency skips.
