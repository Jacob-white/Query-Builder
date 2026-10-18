"""Typing ratchet: the mypy baseline (ignore_errors modules) may only shrink.

`docs/typing_baseline.txt` is the committed ceiling. The `ignore_errors = true`
override in pyproject.toml must be a subset of it, so a new module cannot slip
into the baseline and a graduated module cannot silently regress. When a module
graduates, remove it from BOTH places (and move it into the strict override).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = ROOT / "docs" / "typing_baseline.txt"


def _config() -> dict[str, Any]:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        cfg: dict[str, Any] = tomllib.load(fh)["tool"]["mypy"]
    return cfg


def _modules(override: dict[str, Any]) -> list[str]:
    mods = override["module"]
    return [mods] if isinstance(mods, str) else list(mods)


def _committed_baseline() -> list[str]:
    lines = BASELINE_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _with_flag(flag: str) -> list[str]:
    out: list[str] = []
    for ov in _config().get("overrides", []):
        if ov.get(flag) is True:
            out.extend(_modules(ov))
    return out


def test_global_settings_are_enabled() -> None:
    cfg = _config()
    assert cfg["python_version"] == "3.11"
    for flag in (
        "warn_unused_ignores",
        "warn_redundant_casts",
        "no_implicit_optional",
        "check_untyped_defs",
    ):
        assert cfg[flag] is True, flag
    assert not cfg.get("ignore_missing_imports"), "never ignore imports globally"
    assert not cfg.get("ignore_errors")


def test_baseline_only_shrinks() -> None:
    committed = set(_committed_baseline())
    ignored = _with_flag("ignore_errors")
    assert len(ignored) == len(set(ignored)), "duplicate modules in baseline override"
    added = sorted(set(ignored) - committed)
    assert not added, (
        f"modules newly added to the mypy baseline (not allowed): {added}. "
        "Fix their types instead; the baseline may only shrink."
    )


def test_graduated_modules_are_not_in_the_baseline() -> None:
    overlap = sorted(
        set(_with_flag("disallow_untyped_defs")) & set(_with_flag("ignore_errors"))
    )
    assert not overlap, f"modules both strict and ignored: {overlap}"


def test_committed_list_has_no_stale_entries() -> None:
    # Once a module graduates its line must be deleted from the committed list too,
    # otherwise it could later be re-added to the baseline unnoticed.
    stale = sorted(set(_committed_baseline()) - set(_with_flag("ignore_errors")))
    assert not stale, (
        f"graduated modules still listed in docs/typing_baseline.txt: {stale}. "
        "Delete those lines to lock the gain in."
    )


def test_every_module_is_covered() -> None:
    strict_entries = set(_with_flag("disallow_untyped_defs"))
    ignored_entries = set(_with_flag("ignore_errors"))
    all_entries = strict_entries | ignored_entries

    def _is_covered(mod_name: str) -> bool:
        if mod_name in all_entries:
            return True
        parts = mod_name.split(".")
        for i in range(1, len(parts)):
            if ".".join(parts[:i]) + ".*" in all_entries:
                return True
        return False

    pkg_dir = ROOT / "query_builder"
    uncovered: list[str] = []
    for py_file in sorted(pkg_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        mod_name = ".".join(parts)
        if not _is_covered(mod_name):
            uncovered.append(mod_name)

    assert not uncovered, (
        f"Modules in query_builder/ not covered by strict mypy overrides: {uncovered}"
    )
