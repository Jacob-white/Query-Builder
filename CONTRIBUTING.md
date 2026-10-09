# Contributing to Query-Builder

Thanks for helping. This repository contains three things that are developed and released together:

| Path | What it is | Toolchain |
| :--- | :--- | :--- |
| `query_builder/` | Python engine (PyPI: `query-builder-engine`) | Python >= 3.11, pytest, ruff |
| `packages/react/` | React component library (npm: `@jacob-white/query-builder-react`) | Node >= 22.22.2, pnpm 10, TypeScript, Vite, Vitest |
| `examples/fullstack_starter/` | FastAPI + React example app (not published) | same as above |

Security issues: do **not** open a public issue; follow [SECURITY.md](SECURITY.md).

## Setup

### Python

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,server,django]"
```

`dev` brings pytest, coverage, ruff, DuckDB, SQLAlchemy and Polars; `server` and `django` are the
framework integrations exercised by the test-suite. Install a connector's extra (for example
`pip install -e ".[snowflake]"`) only if you work on that connector. See `pyproject.toml` for the
extras layout rules.

```bash
python -m ruff check .                 # lint (must be clean)
python -m ruff format --check .        # formatting (run `ruff format .` to fix)
python -m pytest -q --cov --cov-report=term-missing:skip-covered   # coverage floor: 99%
```

Some tests shell out to the React package (schema converters), so install it first (below).

### React package

```bash
cd packages/react
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run lint            # 0 errors; warnings are ratcheted (--max-warnings), never raise the number
pnpm run build           # the consumer-simulation tests load dist/, so build before testing
pnpm run test:coverage   # floors: 99% statements / 96% branches / 99% functions / 99% lines
pnpm run check:package   # exports exist and load, publint --strict, are-the-types-wrong
```

### Starter app

```bash
cd packages/react && pnpm install --frozen-lockfile && pnpm run build
cd ../../examples/fullstack_starter/frontend && pnpm install --frozen-lockfile && pnpm run build
```

### Tests against live databases

Connector behaviour against real engines (Docker) is covered by a separate suite that is not part
of the default `pytest` run. See [docs/TESTING_LIVE.md](docs/TESTING_LIVE.md) for how to start the
databases and run it, and [docs/CONNECTORS.md](docs/CONNECTORS.md) for connector status.

## Coding standards

- **Python**: ruff is the single source of truth (`E,F,W,B,I,UP,S` selected, line length 88). Fix
  findings rather than adding `# noqa`; if a suppression is unavoidable, put the reason next to it.
  Type-annotate public functions; the package ships `py.typed`, so annotations are public API.
- **TypeScript**: strict mode. **No `any`** (ESLint `@typescript-eslint/no-explicit-any` is an error):
  use `unknown` and narrow, or a precise type. Prefix intentionally unused arguments with `_`.
  Do not add `eslint-disable` or `@ts-ignore` without a comment explaining why.
- **Regular expressions and ReDoS**: this library parses attacker-influenced SQL, so regexes are a
  security surface.
  - Never nest unbounded quantifiers over overlapping classes (`(a+)+`, `(.*)*`, `\s*\w*\s*` chains).
  - Prefer a small linear scanner / tokenizer to a clever regex for anything that touches SQL text.
  - TypeScript: `regexp/no-super-linear-backtracking` and `no-super-linear-move` are errors in ESLint.
  - Add a timing/linearity test with a hostile input (see `tests/test_regex_linear_timing.py` and
    `packages/react/tests/regex_linear_*.test.ts`) for every new regex that handles user input.
- **Security-sensitive code** (validator, policy, tenant isolation, SSRF checks, connectors): add
  adversarial tests, never loosen a check to make a test pass, and keep errors free of raw driver or
  parser text.
- **Dependencies**: runtime dependencies of the Python core must stay minimal (`sqlparse` today);
  new drivers go in an optional extra named after the connector. The React package has no runtime
  dependencies beyond its `react` peer. Anything new is audited in CI (`pip-audit`, `pnpm audit`).
- **Public API**: anything exported from `query_builder/__init__.py` or
  `packages/react/src/index.ts` is public. Breaking it needs a CHANGELOG entry under **Breaking**.

## Commit and pull-request style

- Conventional-style subjects: `type(scope): imperative summary`, where type is one of
  `feat`, `fix`, `security`, `perf`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`
  (for example `fix(react): make Drizzle call balancing linear`). Keep the subject under ~72 chars
  and explain the *why* in the body.
- One logical change per commit; do not mix formatting sweeps with behavior changes.
- Fill in the pull-request template. CI must be green: lint, format, tests with coverage, the
  package build checks, dependency audit and dependency review.
- Never commit secrets, `.env` files, local databases or build output (`dist/`, `build/`).

## Changelog policy

We follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

- There are two changelogs: `CHANGELOG.md` (the Python engine and repository-wide changes; this is
  the one release notes are cut from) and `packages/react/CHANGELOG.md` (React-package details).
  Mention React-visible changes in both; the root file links to or summarises the React one.
- Every user-visible change adds a bullet under `## Unreleased` in the pull request that makes it,
  using the headings **Breaking**, **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**,
  **Security**, **Tooling** (omit empty headings). Write for users, not for reviewers.
- Purely internal changes (refactors, test-only, CI tweaks that do not change behavior) do not need an entry.
- **At release time** the maintainer promotes `## Unreleased`: rename it to `## [X.Y.Z] - YYYY-MM-DD`,
  add a fresh empty `## Unreleased` above it, and (optionally) add compare links at the bottom of the
  file. The release workflow refuses to publish unless a `## [X.Y.Z]` section for the tagged version
  exists and is non-empty, and uses that section as the GitHub release body. See
  [docs/RELEASING.md](docs/RELEASING.md).
