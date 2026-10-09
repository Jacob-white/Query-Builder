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
