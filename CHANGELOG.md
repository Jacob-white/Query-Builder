# Changelog

## Unreleased

### Breaking
- **Python 3.11+ required** (was declared 3.9+, but the package already imports `typing.Self`
  and uses runtime `X | Y` unions, so 3.9/3.10 never worked). Classifiers, README badge, ruff
  target and `query-builder doctor` now agree.
- **Node 22.22.2+ required** for the React package's toolchain (`jsdom@30` / `undici@8`).
- **React public types tightened** where `any` was removed; see `packages/react/CHANGELOG.md`.
- `RedisQueryCache(socket_timeout=...)` (never released) is now `connect_timeout` / `command_timeout`.

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
- CI (`.github/workflows/ci.yml`): Python 3.11-3.13 on Linux and Windows, React on Node 22/24;
  coverage floors (Python 99%, React 99/96/99/99); ruff `B`, `I`, `UP`, `S` and format check;
  ESLint `no-explicit-any` as an error and a warning ratchet.
- Test environment fixes: `localStorage` shim for newer Node, path-independent TypeScript
  tests, driver isolation for H2/YugabyteDB tests, optional-dependency skips.
