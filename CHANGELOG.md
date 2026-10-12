# Changelog

## Unreleased

### Breaking
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

### Security (key=value DSN egress check)
- **Key=value DSNs bypassed the network-egress check**: `validate_network_target` read a Db2/ODBC
  style `DATABASE=x;HOSTNAME=169.254.169.254;PORT=50000;` string as a single hostname, so the
  cloud-metadata address was **allowed** under the default policy. `HOSTNAME`/`HOST`/`SERVER`/
  `ADDRESS`/`Data Source` and `PORT` are now extracted and validated.

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
