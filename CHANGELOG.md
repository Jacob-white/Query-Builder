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
- Release workflow (`.github/workflows/release.yml`): tag-triggered, dry-run by default, PyPI trusted
  publishing, npm `--provenance`, SBOMs and checksums; see `docs/RELEASING.md`.
- CI: `pip-audit`, `pnpm audit`, dependency review, CycloneDX SBOMs, package build/`twine check`,
  `publint`/`attw`; Dependabot; actions pinned to commit SHAs. Added `CONTRIBUTING.md` and a PR template.
- CI (`.github/workflows/ci.yml`): Python 3.11-3.13 on Linux and Windows, React on Node 22/24;
  coverage floors (Python 99%, React 99/96/99/99); ruff `B`, `I`, `UP`, `S` and format check;
  ESLint `no-explicit-any` as an error and a warning ratchet.
- Test environment fixes: `localStorage` shim for newer Node, path-independent TypeScript
  tests, driver isolation for H2/YugabyteDB tests, optional-dependency skips.
