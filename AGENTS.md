# AGENTS.md - working in Query-Builder

Guidance for AI coding agents and new contributors. [CONTRIBUTING.md](CONTRIBUTING.md) has the full
rules (setup, standards, commit and changelog policy); this file is the short version plus the things
that are not obvious from the code. If something here disagrees with the code, the code wins: fix this
file.

## What this is

A Python library (`query_builder/`) that compiles a JSON query spec to parameterised SQL for ~140
connector classes, validates raw SQL (AST safety), enforces a security policy (tenants, masking,
network egress), and exposes it as a library, an HTTP server, an MCP server and a CLI. A React package
(`packages/react`) provides a visual builder. Python >= 3.11.

## Layout

| Path | Contents |
| :--- | :--- |
| `query_builder/compiler.py`, `dialects/` | spec -> SQL; one dialect per engine family ([docs/DIALECT_GUIDE.md](docs/DIALECT_GUIDE.md)) |
| `query_builder/connectors/` | one module per engine; `base.py` / `async_base.py` hold the shared behaviour |
| `query_builder/security.py`, `egress_guard.py`, `config.py` | network checks, connect-time guard, security profiles and `QB_*` variables |
| `query_builder/ast_validator.py`, `sql_ast.py` | SQL safety validation (fails closed) |
| `query_builder/policy.py` | tenant isolation, column masking |
| `query_builder/server.py`, `mcp_server.py`, `cli.py` | HTTP server, MCP server, CLI |
| `tests/` | unit tests; `tests/integration/` is the live-engine suite (opt-in); `tests/golden/` snapshots |
| `docker/`, `scripts/` | live-engine compose files; `it_batch.py` runner; generators for generated docs |
| `docs/` | guides; `docs/CONNECTORS.md` and `docs/live_results.json` are generated |

## Commands

```bash
pip install -e ".[dev,server,django]"
python -m ruff check .                    # must be clean
python -m ruff format --check .           # `ruff format .` to fix
python -m mypy query_builder              # every module is strict; see docs/TYPING.md
python -m pytest -q --cov --cov-report=term-missing:skip-covered   # coverage floor 99% (pyproject)

# generated files: never hand-edit; regenerate and review the diff
python scripts/gen_connector_status.py                 # docs/CONNECTORS.md   (--check in CI)
python scripts/gen_security_env_table.py               # env table in SECURITY.md (--check; a test enforces it)
QB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden_compiler.py
PYTHONPATH=. python tests/test_golden_dialects.py --update
```

The full suite takes about 8-13 minutes. Run the files you touched first, then everything.

## Rules that are not optional

1. **Security checks are never loosened to make a test pass.** Add an adversarial test, and for new
   security code also a *control* (the same scenario without your change must fail) - see
   `tests/test_egress_guard.py`.
2. **Do not rely on a document; run it.** A documented `QB_ALLOWED_HOSTS` was never read by the code and
   silently did nothing. When you write or change a claim, execute it.
3. **Do not state coverage or pass-rate numbers** you did not just measure. The enforced floors are in
   `pyproject.toml` and `CONTRIBUTING.md`.
4. **Mocks prove little about an engine.** A connector or dialect change that matters is verified against
   the real engine ([docs/TESTING_LIVE.md](docs/TESTING_LIVE.md)). Every engine run live so far had defects
   no mock showed.
5. **Declared limitations need probes.** If an engine cannot do something, declare it with a probe that
   proves the engine rejects it; a bare skip hides real gaps.

## Things that bite

- **The default network policy is permissive.** A connector created without `security=` while
  `QB_SECURITY_PROFILE` is unset allows private networks and does not enforce TLS. Anything that takes
  settings from untrusted input must set a profile. [docs/SECURE_DEPLOYMENT.md](docs/SECURE_DEPLOYMENT.md).
- **Config is read once.** `get_security_config()` caches; `QB_*` variables set later are ignored. In tests
  use `configure_security(...)` / `reset_security_config()`.
- **Unknown `QB_*` variables are ignored without an error.** The valid names are in the generated table in
  `SECURITY.md` section 4.2.
- **Connector methods are wrapped automatically** (`BaseConnector.__init_subclass__`): network validation,
  the egress guard, error mapping. Keep a connector's address under a key the checks recognise
  (`host`, `url`, `dsn`, `hosts`, ...; `is_address_key`), never follow HTTP redirects, and do not start
  your own connecting threads ([docs/ADDING_A_CONNECTOR.md](docs/ADDING_A_CONNECTOR.md)).
- **`get_dialect()` falls back to PostgreSQL** for an unknown name instead of failing.
- **The SQL validator fails closed** on syntax it cannot parse: a new engine's syntax may need an entry in
  `DIALECT_MAP` (`sql_ast.py`) or a normalisation step.
- **Golden files move together.** A change to `BaseDialect` shifts every dialect; review every changed
  entry, not just the engine you touched.
- **Tests that count things.** Connector totals appear in `README.md`, `docs/README.md`, `PROJECT.md` and
  `MISSING_CONNECTORS_PLAN.md` and a test checks them; adding a connector means updating them.
- **Test isolation.** Some tests clear `ConnectorRegistry`; a test that needs a registered class should
  capture it at import time (see `tests/test_egress_guard.py`), not look it up at run time.
- **Ruff versions differ.** `pyproject.toml` allows `ruff>=0.14,<0.17`; formatting can differ between
  versions. If CI's `ruff format --check` disagrees with your local run, match CI's version.
- **Documentation can be ahead of reality.** `TEST_READY.md`, `TEST_INFRA.md`, `PROJECT.md` and
  `MISSING_CONNECTORS_PLAN.md` are historical records (each says so at the top); do not quote their figures.

## Running things on a real machine

- The live suite starts containers only in the compose project **`qb-integration`**, through
  `scripts/it_batch.py` (one engine at a time, with a free-RAM gate). Never stop, restart or remove any
  other container, volume or process on the machine.
- Do not install drivers into the user's environment: use `pip install --target <scratch dir>` and put it
  on `PYTHONPATH` (`;`-separated on Windows).
- Heavy engines (Doris, OceanBase, Db2, Vertica) need several GB of free RAM; check before starting.
- Never point the live suite, or a connector you are testing, at a database you do not own.
- Work on a branch and open a pull request; CI must be green before merging.

## Definition of done

- [ ] change is covered by tests, including an adversarial case for security-relevant code
- [ ] `ruff check .`, `ruff format --check .`, `mypy query_builder` and the full test suite pass
- [ ] generated files regenerated and their diffs reviewed
- [ ] a `CHANGELOG.md` bullet under *Unreleased* for any user-visible change
- [ ] claims in docs were executed, not assumed

## Where to look next

[docs/ADDING_A_CONNECTOR.md](docs/ADDING_A_CONNECTOR.md) - [docs/DIALECT_GUIDE.md](docs/DIALECT_GUIDE.md) -
[docs/TESTING_LIVE.md](docs/TESTING_LIVE.md) - [docs/SECURE_DEPLOYMENT.md](docs/SECURE_DEPLOYMENT.md) -
[SECURITY.md](SECURITY.md) - [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) -
[docs/TYPING.md](docs/TYPING.md) - [docs/api_reference.md](docs/api_reference.md)
