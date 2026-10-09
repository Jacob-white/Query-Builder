"""
Connector verification status registry.
=======================================
Computes, from evidence rather than claims, how well each registered connector
class is verified, and renders the result as JSON / Markdown (``docs/CONNECTORS.md``).

Tiers
-----
``certified``
    The opt-in live conformance suite (``tests/integration``) ran against a real
    engine through this exact connector class and passed in the latest recorded
    run (``docs/live_results.json``).
``verified``
    No live evidence, but the class is exercised by unit tests in ``tests/``
    (and by the registry matrix tests that run for every class).
``experimental``
    Neither of the above.
"""

from __future__ import annotations

import ast
import collections
import importlib
import inspect
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.registry import ConnectorRegistry

CERTIFIED = "certified"
VERIFIED = "verified"
EXPERIMENTAL = "experimental"
UNRATED = "unrated"

_EXTRA_RE = re.compile(r"query-builder-engine\[([\w-]+)\]")
_CONNECT_FUNCS = {
    "connect",
    "_connect",
    "aconnect",
    "connect_async",
    "_ensure_driver",
    "__init__",
}
_STDLIB = set(sys.stdlib_module_names)
_BASES: tuple[type, ...] = (BaseConnector, AsyncBaseConnector)


def repo_root() -> Path | None:
    """Return the source checkout root (has ``tests/`` and ``docs/``) or None."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "tests").is_dir() and (root / "docs").is_dir() else None


def class_key(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _mro_user_classes(cls: type) -> list[type]:
    return [k for k in cls.__mro__ if k not in _BASES and k is not object]


def _class_source(cls: type) -> str:
    try:
        return inspect.getsource(cls)
    except (OSError, TypeError):  # pragma: no cover - dynamically created class
        return ""


def declared_drivers(cls: type) -> tuple[str, ...]:
    """
    Third-party modules the class imports lazily to reach its database.

    Derived from the source of the class (and its connector base classes): the
    ``for mod_name in (...)`` fallback loops plus ``import`` statements found
    inside connect-style methods. Standard-library modules are ignored.
    """
    found: list[str] = []
    for klass in _mro_user_classes(cls):
        try:
            tree = ast.parse(textwrap.dedent(_class_source(klass)))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in _CONNECT_FUNCS:
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.For)
                    and isinstance(sub.target, ast.Name)
                    and sub.target.id == "mod_name"
                    and isinstance(sub.iter, (ast.Tuple, ast.List))
                ):
                    found += [
                        e.value
                        for e in sub.iter.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                elif isinstance(sub, ast.Import):
                    found += [a.name for a in sub.names]
                elif isinstance(sub, ast.ImportFrom) and sub.module and not sub.level:
                    found.append(sub.module)
        if found:
            break
    drivers = [
        m
        for m in dict.fromkeys(found)
        if m.split(".")[0] not in _STDLIB and m.split(".")[0] != "query_builder"
    ]
    return tuple(drivers)


def declared_extra(cls: type) -> str | None:
    """The ``query-builder-engine[<extra>]`` install hint the class documents."""
    for klass in _mro_user_classes(cls):
        match = _EXTRA_RE.search(_class_source(klass))
        if match:
            return match.group(1)
    try:
        module_src = inspect.getsource(sys.modules[cls.__module__])
    except (OSError, TypeError, KeyError):  # pragma: no cover
        return None
    match = _EXTRA_RE.search(module_src)
    return match.group(1) if match else None


def pyproject_extras(root: Path | None = None) -> set[str]:
    """Optional-dependency group names declared in ``pyproject.toml``."""
    import tomllib

    base = root or repo_root()
    if base is None or not (base / "pyproject.toml").is_file():
        return set()
    data = tomllib.loads((base / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data.get("project", {}).get("optional-dependencies", {}))


def collect_connectors() -> list[dict[str, Any]]:
    """One record per registered connector class, aliases grouped (no tier yet)."""
    importlib.import_module("query_builder.connectors")
    names: dict[type, list[str]] = collections.defaultdict(list)
    for name, cls in ConnectorRegistry._registry.items():
        names[cls].append(name)

    from query_builder.dialects import list_dialects

    dialects = set(list_dialects())
    records: list[dict[str, Any]] = []
    by_module: dict[str, list[type]] = collections.defaultdict(list)
    for cls in names:
        by_module[cls.__module__].append(cls)

    for cls, aliases in names.items():
        is_async = issubclass(cls, AsyncBaseConnector)
        siblings = [k for k in by_module[cls.__module__] if k is not cls]
        pair = [
            k
            for k in siblings
            if issubclass(k, AsyncBaseConnector) != is_async
            and getattr(k, "dialect_name", None) == cls.dialect_name
        ]
        non_async_names = sorted(
            (a for a in aliases if not a.startswith("async_")), key=len
        )
        primary = non_async_names[0] if non_async_names else sorted(aliases, key=len)[0]
        records.append(
            {
                "key": class_key(cls),
                "class": cls.__name__,
                "module": cls.__module__,
                "name": primary,
                "aliases": sorted(set(aliases) - {primary}),
                "mode": "async" if is_async else "sync",
                "counterpart": class_key(pair[0]) if pair else None,
                "dialect": cls.dialect_name,
                "dialect_registered": cls.dialect_name in dialects,
                "extra": declared_extra(cls),
                "drivers": list(declared_drivers(cls)),
            }
        )
    records.sort(key=lambda r: (r["module"], r["mode"] == "async", r["class"]))
    return records


def unit_test_references(
    root: Path | None = None, connectors: list[dict[str, Any]] | None = None
) -> dict[str, int]:
    """Map class name -> number of default-suite test files that mention it."""
    base = root or repo_root()
    counts: dict[str, int] = collections.defaultdict(int)
    if base is None:
        return {}
    texts = [
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted((base / "tests").glob("test_*.py"))
    ]
    idents = [set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", t)) for t in texts]
    for rec in connectors if connectors is not None else collect_connectors():
        counts[rec["key"]] = sum(1 for ids in idents if rec["class"] in ids)
    return dict(counts)


def load_live_results(root: Path | None = None) -> dict[str, Any]:
    """Latest recorded live run (``docs/live_results.json``) or an empty record."""
    base = root or repo_root()
    path = (base / "docs" / "live_results.json") if base else None
    if path is None or not path.is_file():
        return {"run_at": None, "engines": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _live_index(live: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for engine, rec in live.get("engines", {}).items():
        for key in rec.get("connectors", []):
            index[key] = {"engine": engine, **rec}
    return index


def compute_tier(
    key: str,
    live_index: dict[str, dict[str, Any]],
    unit_refs: dict[str, int] | None,
) -> tuple[str, str]:
    """Return ``(tier, evidence)`` for a connector class key."""
    live = live_index.get(key)
    if live and live.get("passed", 0) > 0 and live.get("failed", 0) == 0:
        return CERTIFIED, (
            f"live conformance passed ({live['passed']} passed, "
            f"{live.get('skipped', 0)} skipped) on {live.get('version') or '?'}"
        )
    if unit_refs is None:
        return UNRATED, "no source checkout: unit-test evidence unavailable"
    if unit_refs.get(key, 0) > 0:
        return (
            VERIFIED,
            f"unit tests in {unit_refs[key]} test file(s) + registry matrix",
        )
    return EXPERIMENTAL, "no unit tests and no live run"


def build_report(root: Path | None = None) -> dict[str, Any]:
    """Full machine-generated status report (JSON-serializable)."""
    base = root or repo_root()
    live = load_live_results(base)
    live_index = _live_index(live)
    connectors = collect_connectors()
    unit_refs = unit_test_references(base, connectors) if base else None
    extras = pyproject_extras(base) if base else set()
    for rec in connectors:
        tier, evidence = compute_tier(rec["key"], live_index, unit_refs)
        rec["tier"] = tier
        rec["evidence"] = evidence
        rec["extra_declared_in_pyproject"] = (
            None if (rec["extra"] is None or not extras) else rec["extra"] in extras
        )
        hit = live_index.get(rec["key"])
        rec["live"] = (
            {
                "engine": hit["engine"],
                "version": hit.get("version"),
                "passed": hit.get("passed"),
                "failed": hit.get("failed"),
                "skipped": hit.get("skipped"),
            }
            if hit
            else None
        )
    tiers = collections.Counter(r["tier"] for r in connectors)
    return {
        "generated_for": "query-builder connector status",
        "live_run_at": live.get("run_at"),
        "totals": {
            "classes": len(connectors),
            "sync": sum(r["mode"] == "sync" for r in connectors),
            "async": sum(r["mode"] == "async" for r in connectors),
            "registered_names": len(ConnectorRegistry._registry),
            "tiers": dict(tiers),
        },
        "connectors": connectors,
    }


def render_table(report: dict[str, Any]) -> str:
    """Compact plain-text table for the CLI."""
    rows = [("CLASS", "MODE", "TIER", "EXTRA", "NAMES")]
    for r in report["connectors"]:
        rows.append(
            (
                r["class"],
                r["mode"],
                r["tier"],
                r["extra"] or "-",
                ", ".join([r["name"], *r["aliases"]]),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:4]))
        + "  "
        + row[4]
        for row in rows
    ]
    t = report["totals"]
    lines.append("")
    lines.append(
        f"{t['classes']} classes ({t['sync']} sync / {t['async']} async), "
        f"{t['registered_names']} registered names; tiers: "
        + ", ".join(f"{k}={v}" for k, v in sorted(t["tiers"].items()))
    )
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    """Render ``docs/CONNECTORS.md``."""
    t = report["totals"]
    tiers = t["tiers"]
    out = [
        "# Connector Status",
        "",
        "<!-- GENERATED by scripts/gen_connector_status.py - do not edit by hand. -->",
        "",
        f"There are **{t['classes']} connector classes** "
        f"({t['sync']} sync, {t['async']} async) reachable through "
        f"**{t['registered_names']} registered names** (aliases included).",
        "Each class is listed once below with its aliases grouped.",
        "",
        "## Verification tiers",
        "",
        "Tiers are computed from evidence (see `docs/TESTING_LIVE.md`), never claimed:",
        "",
        "| Tier | Meaning | Classes |",
        "| --- | --- | --- |",
        "| `certified` | The live conformance suite (`tests/integration`) ran against a real "
        "engine through this class and passed in the latest recorded run. "
        f"| {tiers.get(CERTIFIED, 0)} |",
        "| `verified` | No live run; the class is exercised by unit tests and the registry "
        f"matrix tests, all against mocks. | {tiers.get(VERIFIED, 0)} |",
        "| `experimental` | Neither live nor unit-test evidence. "
        f"| {tiers.get(EXPERIMENTAL, 0)} |",
        "",
    ]
    live_at = report.get("live_run_at")
    out.append(
        f"Latest recorded live run: **{live_at}**."
        if live_at
        else "No live run recorded."
    )
    out.append("")
    live_rows = sorted(
        {
            (
                r["live"]["engine"],
                r["live"]["version"] or "?",
                r["live"]["passed"],
                r["live"]["failed"],
                r["live"]["skipped"],
            )
            for r in report["connectors"]
            if r["live"]
        }
    )
    if live_rows:
        out += [
            "### Engines in the latest live run",
            "",
            "| Engine | Version | Passed | Failed | Skipped |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        out += [
            f"| {e} | {str(v).splitlines()[0][:80]} | {p} | {f} | {s} |"
            for e, v, p, f, s in live_rows
        ]
        out.append("")
    out += [
        "## Connectors",
        "",
        "| Class | Mode | Tier | Install extra | Registered names |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report["connectors"]:
        extra = f"`[{r['extra']}]`" if r["extra"] else "none"
        names = ", ".join(f"`{n}`" for n in [r["name"], *r["aliases"]])
        out.append(
            f"| `{r['class']}` | {r['mode']} | {r['tier']} | {extra} | {names} |"
        )
    out.append("")
    return "\n".join(out)
