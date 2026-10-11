# Typing

`query_builder` ships a `py.typed` marker, so its annotations are a public promise.
They are enforced with [mypy](https://mypy.readthedocs.io) through a **ratchet**: modules
that are clean are locked strict, and the list of modules that are not yet checked can only
shrink.

## How it is enforced

- **Config:** `[tool.mypy]` in `pyproject.toml` (Python 3.11, `warn_unused_ignores`,
  `warn_redundant_casts`, `no_implicit_optional`, `check_untyped_defs`).
- **Strict modules:** a `[[tool.mypy.overrides]]` block turns on `disallow_untyped_defs`,
  `disallow_incomplete_defs` and `disallow_any_generics` for every graduated module.
- **Baseline:** a second override sets `ignore_errors = true` for the modules not yet done.
  It is mirrored in `docs/typing_baseline.txt`.
- **CI:** the Python job runs `python -m mypy query_builder` (ubuntu / Python 3.13 leg only)
  and fails on any error.
- **Ratchet test:** `tests/test_typing_ratchet.py` fails if the `ignore_errors` list contains
  a module that is not in `docs/typing_baseline.txt` (nothing new may join the baseline), if a
  module is both strict and ignored, or if a graduated module is still listed in the committed
  file (so a finished module cannot quietly be re-added later).
- **Third-party imports:** never ignored globally. `redis` and `yaml` (optional dependencies)
  have scoped `ignore_missing_imports` overrides; `types-PyYAML` is a dev dependency.
- **`type: ignore`:** must carry a specific error code and a reason comment.

Run it locally:

```
python -m pip install -e ".[dev]"
python -m mypy query_builder
```

## Modules still in the baseline

The core engine is fully graduated (compiler, parser, sql_ast, ast_validator, dialects, server,
cli). What remains is the optional-dependency surface, where fallback imports such as
`try: import x / except ImportError: x = None` need careful typing:

1. `connectors/**` (`base` and `async_base` first, then each connector; optional vendor SDKs
   need scoped `ignore_missing_imports` overrides or stubs)
2. `integrations/*` (`fastapi`, `django`, ...; optional framework imports)

The authoritative list is `docs/typing_baseline.txt`.

## Graduating a module

1. Remove it from the `ignore_errors` override in `pyproject.toml`, add it to the strict
   override, and run `python -m mypy query_builder`.
2. Fix the errors with real types: narrow `Optional`s, add missing returns, parametrize
   generics, use `TypedDict` / `Protocol` / dataclasses instead of `Any`. Avoid `type: ignore`;
   when unavoidable use `# type: ignore[code]  # reason`.
3. Delete the module's line from `docs/typing_baseline.txt`.
4. If the fix changes behavior, add a regression test (see `tests/test_typing_regressions.py`).
5. Run `python -m pytest tests/test_typing_ratchet.py` and the full suite.
