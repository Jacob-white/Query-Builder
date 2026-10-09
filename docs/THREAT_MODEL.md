# Threat model

This document says what Query-Builder protects, against whom, what each layer actually
guarantees, and, just as important, what it does **not** guarantee. If a statement here is
stronger than the code, that is a bug: please report it.

## 1. Assets

| Asset | Why it matters |
| --- | --- |
| Data of other tenants / owners | The core promise of the multi-tenant policy layer. |
| Restricted tables and schemas | Credentials, sessions, catalogs (`auth_user`, `pg_shadow`, `mysql.user`, `information_schema`, ...). |
| Database integrity and availability | No writes, DDL, file access or code execution through a "read-only" query path. |
| The network the server runs in | Cloud metadata, internal services reachable from the host that opens the connection (SSRF). |
| Credentials in config / error messages | Scrubbed from logs and exceptions. |

## 2. Attacker model

In scope: an authenticated or semi-trusted **client** (an end user, an LLM agent, an API
caller) who controls

* the SQL text passed to the validator / the connectors' `sql=` argument,
* a `QuerySpec` (filters, joins, columns, combiners, parentheses flags),
* connection settings in multi-tenant / "bring your own database" deployments (host, port, URL).

Out of scope: an attacker with direct database credentials, code execution in the host
process, control of the operator's configuration or environment variables, a malicious
database driver, side channels (timing, error oracles), and denial of service by *legitimate*
but expensive read-only queries (use statement timeouts and row limits; they bound but do not
eliminate this).

## 3. Layers and what each guarantees

The layers are independent on purpose; a query is accepted only if **every** applicable
layer accepts it.

### 3.1 Lexer / legacy layer (`query_builder/ast_validator.py`)

sqlparse plus a single-pass lexer evaluated under every plausible dialect interpretation
(backslash escapes, `#` comments, dollar quotes, bracket identifiers, nested comments, MySQL's
`--` rule), token-based relation detection, a deny-list of SQL-executing / file-reading
functions and regex fall-backs.

*Guarantees:* a query that this layer accepts contains one statement, with a `SELECT`/`WITH`
root, no mutation keywords, no denied function and no restricted relation **in any of the
lexical interpretations it models**.

*Does not guarantee:* agreement with a specific engine's parser for syntax it does not model.
It is a conservative approximation (it rejects what it cannot classify), not a parser.

### 3.2 sqlglot structural layer (`query_builder/sql_ast.py`)

Parses the statement into a syntax tree and applies an **allowlist** policy: exactly one
statement; the root is a query (`SELECT`, set operation, parenthesised query); no DML / DDL /
`Command` / `INTO` / locking / pragma node anywhere in the tree; no denied function in any
position (including table functions and qualified names); no real relation in a restricted
table or schema. CTE aliases are resolved with correct scoping (a CTE named like a restricted
table neither hides the real table inside its own definition nor triggers a false alarm), and
file-looking relation names (`FROM 'data.csv'`, `s3://...`) are denied.

*Failure policy:* **fail closed.** If sqlglot cannot parse the text under any candidate
dialect (or raises, or hits the recursion limit) the query is rejected. There is deliberately
no "legacy layer says it is trivially safe" exception. For an unknown or missing `dialect`,
the query is analysed under every dialect in `sql_ast.FALLBACK_DIALECTS` and the findings are
unioned; it is rejected if any interpretation that parses is unsafe, and counts as unparsable
only if none parses.

*Does not guarantee:* that sqlglot's grammar equals the target engine's grammar. When
`dialect=None`, a dialect that fails to parse is ignored as long as another one parses; the
legacy layer (which models the lexical differences) is what covers that gap. Pass the real
`dialect` whenever it is known (connectors do).

### 3.3 Differential and fuzz evidence

The claim "no false negatives" is *tested*, not argued: see section 6. The oracles are the
real parsers of SQLite (authorizer + trace), PostgreSQL (`pglast` / libpg_query) and DuckDB
(`extract_statements`, `json_serialize_sql`). This is evidence, not a proof: it covers the
grammar fragment the generators produce, for three engines.

### 3.4 Policy enforcement (`policy.py`, `compiler.py`)

Tenant and row-level predicates are injected with an internal `_enforced` marker and emitted
by the compiler as standalone `AND`-ed clauses **outside** the client's filter group
(`WHERE tenant = ? AND (client filters)`). Client-supplied `_enforced` flags are stripped,
unbalanced client parentheses cannot close the wrapping group, and combiners are whitelisted
to `AND`/`OR`. Tests: an AST-based architectural test (every injection site sets the marker;
every `QueryCompiler(` call site is classified) and a property test that random client filter
garbage never returns another tenant's rows on a real SQLite database.

*Does not guarantee:* isolation on entry points that never call the policy. Today these are
the trusted/operator surfaces listed in `tests/test_policy_architecture.py::LEDGER` as
`no-tenant-context` (CLI, MCP tool server, AI agent tooling, `ConnectionPool` raw execution);
they must sit behind your own authentication and must not be exposed to tenants. Raw SQL sent
by a tenant (`sql=`) is *validated*, but it is **not** rewritten to add tenant predicates: use
specs, or a database role with row-level security, for tenant isolation of raw SQL.

### 3.5 Database-side read-only session (`apply_read_only`)

`BaseConnector.connect()` calls `apply_read_only(connection)` whenever
`security.execution.enforce_read_only_session` is on (default), once per connection, so a
connector cannot forget it; a failure fails the connection closed.

| Engine | Mechanism | Strength |
| --- | --- | --- |
| SQLite | `PRAGMA query_only = ON`; existing files are additionally opened with a `mode=ro` URI | Enforced by the engine. Setup through the same connector must opt out. |
| DuckDB | File databases opened with `read_only=True` | Enforced by the engine. **In-memory databases and caller-supplied connections cannot be switched after the fact.** |
| PostgreSQL, CockroachDB, TimescaleDB, Neon, AlloyDB | `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`, committed | Enforced; a role with `SET default_transaction_read_only = off` rights can undo it. |
| Redshift | Same statement | Best effort (driver/version dependent). |
| MySQL, MariaDB, TiDB | `SET SESSION TRANSACTION READ ONLY` | Enforced for ordinary transactions; `SUPER`-class accounts can lift it. |
| ClickHouse | `readonly = 2` client setting | Enforced, the setting itself is locked. `readonly = 1` was rejected because it also forbids the connector's own `SET max_execution_time`. |
| SQL Server | none | **No session-level read-only mode exists.** `ApplicationIntent=ReadOnly` only routes to a readable secondary and does not block writes on a primary; `pymssql` does not support it. Use a `db_datareader`-only login. |
| SingleStore, QuestDB, Materialize, RisingWave, and all other connectors | none | No documented mechanism; `read_only_support == "none"`. Use a read-only database role. |

Every connector declares `read_only_support` (`enforced` / `best_effort` / `none`); a test
fails if one claims enforcement without a mechanism. The strongest guarantee is always a
**database user that only has read privileges**; the session setting is defence in depth.

### 3.6 SSRF / DNS-rebinding protection (`security.py`)

`validate_network_target` blocks loopback, RFC 1918, link-local, CGNAT, multicast, reserved,
IPv6 ULA / site-local / link-local, IPv4-mapped, NAT64, 6to4, Teredo and IPv4-compatible
addresses (the embedded IPv4 is checked), and cloud metadata endpoints and host names
(trailing-dot and ideographic-dot variants included; metadata is forbidden even when private
networks are allowed). Every address a name resolves to is validated.

`resolve_and_validate_target` resolves a name **once**, validates every returned address and
returns the validated address to connect to. Connectors use it on the host-based connect path:
the PostgreSQL family connects with libpq's `hostaddr` set to the validated address (the host
name stays for TLS verification), so no second DNS lookup happens. Resolution goes through one
injectable resolver (`set_dns_resolver`) so rebinding sequences are testable.

*Limits:* pinning is only possible where the driver accepts a numeric address next to the host
name. **Not pinned** (validated, but the driver resolves again): URL/DSN-based drivers, HTTP
clients (ClickHouse HTTP, Elasticsearch, NLQ providers), MySQL/MSSQL/Oracle/other drivers, and
all async connectors. For those the rebinding window remains; mitigate with an egress firewall
or a pinned internal resolver. Unresolvable names pass validation by default so the driver can
fail on its own; set `network.fail_closed_on_dns_error = True` to reject them (which closes the
"NXDOMAIN now, private address later" variant for pinned drivers).

## 4. Explicit non-guarantees and known limits

* **Dialect coverage.** About 90 dialect names are accepted; sqlglot models roughly 30 engines.
  The rest are mapped to the closest family or analysed under every fallback dialect.
  Engine-specific syntax outside both models is rejected (fail closed) rather than trusted, which
  can produce false positives for exotic but legitimate SQL.
* **Parser differentials.** The validator cannot be *proved* equal to each database's parser.
  Differences are bounded by the differential suites, not eliminated.
* **Features that cannot be enforced at the SQL layer:** engine-side functions added by
  extensions or user-defined functions with side effects; `SELECT` statements that trigger
  side effects through a function it cannot recognise; read access to data the connecting
  role can already read; resource exhaustion by legitimate queries; information leakage
  through error messages of the database.
* **`WITH RECURSIVE`, `FOR UPDATE`, `SELECT ... INTO`, `VALUES`, `TABLE x`-in-set-operations,
  `EXPLAIN`, `SHOW`, `PRAGMA`** are rejected by design in the default policy.
* The restricted-table list is a deny-list of well-known names. It is not an inventory of your
  schema: configure `restricted_tables` / `allowed_schemas` for your own sensitive tables, and
  prefer a database role that cannot see them at all.
* Comments between the words of a multi-word keyword (`GROUP /* c */ BY`) are handled by a
  comment-stripped re-parse; nested block comments are deliberately rejected as ambiguous.

## 5. Reporting issues

Follow [SECURITY.md](../SECURITY.md): `security@hobbyhabbit.com` or a private GitHub security
advisory. A minimal reproducer (the SQL text or `QuerySpec`, the dialect, and the engine's
behaviour) is ideal. **False negatives are security bugs; false positives are ordinary bugs.**
When you fix one, add the minimal reproducer to
`tests/test_validator_fuzz_regressions.py` (or `tests/test_ssrf_pinning.py`, ...).

## 6. Running the differential and fuzz suites

```bash
# fast profile: deterministic (derandomize=True), whole suite well under a minute
python -m pytest -m fuzz -q

# everything fuzz-related with timings
python -m pytest -m fuzz -q --durations=10

# deep profile for occasional runs (12k examples per property by default, randomised)
HYPOTHESIS_PROFILE=deep python -m pytest -m fuzz -q
FUZZ_DEEP_EXAMPLES=50000 HYPOTHESIS_PROFILE=deep python -m pytest -m fuzz -q \
    tests/test_validator_differential_sqlite.py
```

Suites (all marked `fuzz`): `tests/test_validator_differential_sqlite.py` (SQLite authorizer /
trace oracle), `..._postgres.py` (`pglast`), `..._duckdb.py` (DuckDB parser),
`tests/test_validator_fuzz.py` (robustness and metamorphic properties). The generators live in
`tests/_sqlgen.py` (composable grammar with comments in every position, every quoting style, set
operations, CTEs, joins, table functions, stacked statements, plus mutation of a corpus of
known bypasses). `tests/test_validator_false_positives.py` measures the false-positive rate on
~200 realistic benign analytical queries (`tests/_benign_corpus.py`); it must stay at 0.
`pglast` and `hypothesis` are dev dependencies; the PostgreSQL oracle skips if `pglast` is not
installed. Live-database read-only checks are `integration`-marked
(`tests/integration/test_readonly_<engine>.py`, `QB_IT_<ENGINE>_*` environment variables) and
skip when the engine is unreachable.
