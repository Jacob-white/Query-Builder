"""
Connector verification status registry.
=======================================
Computes, from evidence rather than claims, how well each registered connector
class is verified, and renders the result as JSON / Markdown (``docs/CONNECTORS.md``).

Tiers
-----
``certified``
    The opt-in live conformance suite (``tests/integration``) ran against a real
    engine through this exact connector class with ZERO failures AND every applicable
    CORE category of the engine's family (``SQL_CORE`` / ``NATIVE_CORE``) has at least one
    pass or a probe-verified limitation, with no unverified (``declared_unverified``) skip
    in a core category. Tiers measure testing DEPTH, not merely "something passed".
``basic``
    A real engine passed at least one live test with zero failures, but the certified bar
    is not met: shallow coverage (e.g. smoke-level only), unverified skips, or an old-format
    report that carries no per-category evidence.
``emulated``
    Like the live tiers but against an emulator of the service; the evidence string shows
    whether the depth bar was met.
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
BASIC = "basic"
EMULATED = "emulated"
VERIFIED = "verified"
EXPERIMENTAL = "experimental"
UNRATED = "unrated"

#: Check categories. A live report attributes every result to one of these (see
#: ``tests/integration/categories.py``); ``certified`` needs every applicable CORE one.
SQL_CORE: tuple[str, ...] = (
    "connect",
    "introspect_tables",
    "introspect_columns",
    "introspect_pk_fk",
    "read_projection",
    "filters",
    "ordering",
    "pagination",
    "aggregates",
    "joins",
    "subquery_cte",
    "parameter_safety",
    "identifier_quoting",
    "null_handling",
    "write_refused",
    "error_mapping",
    "statement_timeout",
    "async_parity",
)
NATIVE_CORE: tuple[str, ...] = (
    "connect",
    "introspect",
    "read_basic",
    "read_filtered",
    "ordering",
    "pagination",
    "value_safety",
    "write_refused",
    "error_mapping",
    "async_parity",
)
CORE_BY_KIND: dict[str, tuple[str, ...]] = {"sql": SQL_CORE, "native": NATIVE_CORE}
SKIP_KINDS = ("verified_limitation", "declared_unverified", "environment")

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


def _module_level_driver_loops(cls: type) -> list[str]:
    """Driver modules named by ``for mod_name in (...)`` loops in the TOP-LEVEL functions of
    the module that defines ``cls``. Connectors often factor driver loading into a helper such
    as ``_load_driver()`` outside the class; the same loop convention applies there."""
    module = sys.modules.get(cls.__module__)
    try:
        tree = ast.parse(inspect.getsource(module)) if module else None
    except (OSError, TypeError, SyntaxError):  # pragma: no cover - no source available
        return []
    if tree is None:
        return []
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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
    return found


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
            # The ``for mod_name in (...)`` driver-fallback loop is a deliberate convention and
            # counts wherever it lives (connectors often factor it into a ``_load_driver``
            # helper); plain ``import`` statements only count inside connect-style methods.
            in_connect = node.name in _CONNECT_FUNCS
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
                elif in_connect and isinstance(sub, ast.Import):
                    found += [a.name for a in sub.names]
                elif (
                    in_connect
                    and isinstance(sub, ast.ImportFrom)
                    and sub.module
                    and not sub.level
                ):
                    found.append(sub.module)
        if found:
            break
    if not found:
        found += _module_level_driver_loops(cls)
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
        # shipped connectors only (tests/plugins may register their own classes)
        if cls.__module__.startswith("query_builder.connectors."):
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


def merge_live_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Combine live-suite reports (e.g. a host run plus a Linux-container run).

    Engines are keyed by name (later reports win); each engine keeps the
    ``run_at``/``platform`` of the run that produced it.
    """
    merged: dict[str, Any] = {"run_at": None, "engines": {}}
    for report in reports:
        for name, rec in report.get("engines", {}).items():
            merged["engines"][name] = {
                **rec,
                # keep per-engine provenance that is already recorded; else use the report's
                "run_at": rec.get("run_at") or report.get("run_at"),
                "platform": rec.get("platform") or report.get("platform"),
                "python": rec.get("python") or report.get("python"),
            }
        stamp = report.get("run_at")
        if stamp and (merged["run_at"] is None or stamp > merged["run_at"]):
            merged["run_at"] = stamp
    return merged


def record_live(reports: list[dict[str, Any]], root: Path | None = None) -> Path:
    """Write ``docs/live_results.json``: the evidence behind the ``certified`` tier."""
    base = root or repo_root()
    if base is None:
        raise RuntimeError("recording a live run needs a source checkout")
    path = base / "docs" / "live_results.json"
    # Merge INTO the evidence already recorded: recording one family must not erase the others.
    previous = load_live_results(base)
    path.write_text(
        json.dumps(merge_live_reports([previous, *reports]), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def core_required(rec: dict[str, Any]) -> list[str]:
    """Core categories that apply to this engine record (``rec['core']`` wins)."""
    explicit = rec.get("core")
    if explicit:
        return list(explicit)
    kind = rec.get("family_kind") or "sql"
    core = CORE_BY_KIND.get(kind, SQL_CORE)
    # a record that does not list its applicable core cannot say whether an async class
    # exists: only require async_parity when it carries evidence for it
    cats = rec.get("categories") or {}
    return [c for c in core if c != "async_parity" or c in cats]


def depth(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Per-engine depth evidence, or None for an old-format report (no ``categories``)."""
    cats = rec.get("categories")
    if not isinstance(cats, dict) or not cats:
        return None
    required = core_required(rec)
    covered: list[str] = []
    missing: list[str] = []
    unverified: list[str] = []
    for name in required:
        c = cats.get(name) or {}
        skipped = c.get("skipped") or {}
        if c.get("failed", 0):
            missing.append(name)
            continue
        if skipped.get("declared_unverified", 0):
            unverified.append(name)
        if c.get("passed", 0) > 0 or skipped.get("verified_limitation", 0) > 0:
            covered.append(name)
        else:
            missing.append(name)
    limits = rec.get("limitations") or {}
    return {
        "required": required,
        "covered": covered,
        "missing": missing,
        "unverified": unverified,
        "total": len(required),
        "declared_unverified": sorted(limits.get("declared_unverified", [])),
        "verified_limitations": sorted(limits.get("verified", [])),
        "meets_bar": not missing and not unverified,
    }


def core_label(d: dict[str, Any] | None) -> str:
    """``12/14 core categories`` (or ``no category evidence`` for an old-format report)."""
    if d is None:
        return "no category evidence"
    return f"{len(d['covered'])}/{d['total']} core categories"


def _live_index(live: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Best live evidence per connector class.

    Several engines can exercise the same class (e.g. SQL Server and the Synapse cloud stub
    both use ``MSSQLConnector``); keep the strongest result instead of whichever engine
    happens to be listed last: a clean pass beats a failing run, a real service beats an
    emulator, a met depth bar beats a shallow run, then more covered core categories, then
    more passes.
    """

    def strength(rec: dict[str, Any]) -> tuple[bool, bool, bool, int, int]:
        d = depth(rec)
        return (
            rec.get("failed", 0) == 0 and rec.get("passed", 0) > 0,
            not rec.get("emulated", False),
            bool(d and d["meets_bar"]),
            len(d["covered"]) if d else 0,
            rec.get("passed", 0),
        )

    index: dict[str, dict[str, Any]] = {}
    for engine, rec in live.get("engines", {}).items():
        for key in rec.get("connectors", []):
            current = index.get(key)
            if current is None or strength(rec) > strength(current):
                index[key] = {"engine": engine, **rec}
    return index


def compute_tier(
    key: str,
    live_index: dict[str, dict[str, Any]],
    unit_refs: dict[str, int] | None,
) -> tuple[str, str]:
    """Return ``(tier, evidence)`` for a connector class key."""
    live = live_index.get(key)
    caveat = ""
    if live and live.get("passed", 0) > 0:
        failed, known = live.get("failed", 0), live.get("xfailed", 0)
        if failed == 0 and known == 0:
            counts = (
                f"({live['passed']} passed, {live.get('skipped', 0)} skipped) "
                f"on {live.get('version') or '?'}"
            )
            d = depth(live)
            if d is None:
                depth_text = "old-format report: no per-category evidence"
            else:
                depth_text = core_label(d)
                if d["missing"]:
                    depth_text += f"; missing {', '.join(d['missing'])}"
                if d["unverified"]:
                    depth_text += f"; unverified skips in {', '.join(d['unverified'])}"
            if live.get("emulated"):
                bar = "depth bar met" if d and d["meets_bar"] else "depth bar not met"
                return EMULATED, (
                    "conformance passed against an emulator, not the real service "
                    f"{counts}; {depth_text}; {bar}"
                )
            if d is not None and d["meets_bar"]:
                return CERTIFIED, f"live conformance passed {counts}; {depth_text}"
            return BASIC, f"live tests passed {counts}, depth bar not met: {depth_text}"
        caveat = f"; live run had {failed} failed / {known} known issues"
    if unit_refs is None:
        return UNRATED, "no source checkout: unit-test evidence unavailable"
    if unit_refs.get(key, 0) > 0:
        return (
            VERIFIED,
            f"unit tests in {unit_refs[key]} test file(s) + registry matrix{caveat}",
        )
    return EXPERIMENTAL, f"no unit tests and no passing live run{caveat}"


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
                "xfailed": hit.get("xfailed", 0),
                "depth": depth(hit),
            }
            if hit
            else None
        )
    live_engines = [
        {
            "engine": name,
            "version": rec.get("version"),
            "passed": rec.get("passed", 0),
            "failed": rec.get("failed", 0),
            "xfailed": rec.get("xfailed", 0),
            "skipped": rec.get("skipped", 0),
            "depth": depth(rec),
            "run_at": rec.get("run_at") or live.get("run_at"),
            "platform": rec.get("platform"),
        }
        for name, rec in sorted(live.get("engines", {}).items())
    ]
    tiers = collections.Counter(r["tier"] for r in connectors)
    return {
        "generated_for": "query-builder connector status",
        "live_run_at": live.get("run_at"),
        "live_engines": live_engines,
        "totals": {
            "classes": len(connectors),
            "sync": sum(r["mode"] == "sync" for r in connectors),
            "async": sum(r["mode"] == "async" for r in connectors),
            "registered_names": sum(1 + len(r["aliases"]) for r in connectors),
            "tiers": dict(tiers),
        },
        "connectors": connectors,
    }


def render_table(report: dict[str, Any]) -> str:
    """Compact plain-text table for the CLI."""
    rows = [("CLASS", "MODE", "TIER", "CORE", "UNVERIFIED", "EXTRA", "NAMES")]
    for r in report["connectors"]:
        live = r.get("live") or {}
        d = live.get("depth")
        rows.append(
            (
                r["class"],
                r["mode"],
                r["tier"],
                f"{len(d['covered'])}/{d['total']}" if d else "-",
                str(len(d["declared_unverified"])) if d else "-",
                r["extra"] or "-",
                ", ".join([r["name"], *r["aliases"]]),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(6)]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:6]))
        + "  "
        + row[6]
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


def _unverified_cell(d: dict[str, Any] | None) -> str:
    """``3: having, right_join, ...`` (declared limitations nobody has probed)."""
    if d is None:
        return "-"
    names = d.get("declared_unverified") or []
    if not names:
        return "0"
    shown = ", ".join(f"`{n}`" for n in names[:6])
    more = f", +{len(names) - 6} more" if len(names) > 6 else ""
    return f"{len(names)}: {shown}{more}"


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
        "| `certified` | A real engine ran the live suite through this class with zero "
        "failures AND every applicable core category (see legend) has a pass or a "
        "probe-verified limitation, with no unverified skip in a core category. "
        f"| {tiers.get(CERTIFIED, 0)} |",
        "| `basic` | A real engine passed live tests with zero failures, but the depth bar "
        "is not met (shallow coverage, unverified skips, or an old report without "
        f"category evidence). | {tiers.get(BASIC, 0)} |",
        "| `emulated` | The live conformance suite passed against a vendor/community "
        "EMULATOR of the service, not the real service (e.g. Firestore, Bigtable, Spanner, "
        f"BigQuery, DynamoDB-local). | {tiers.get(EMULATED, 0)} |",
        "| `verified` | No live run; the class is exercised by unit tests and the registry "
        f"matrix tests, all against mocks. | {tiers.get(VERIFIED, 0)} |",
        "| `experimental` | Neither live nor unit-test evidence. "
        f"| {tiers.get(EXPERIMENTAL, 0)} |",
        "",
        "**Legend: tiers measure testing depth, not just that something passed.** A live "
        "result is attributed to a check *category*. SQL engines must cover: "
        + ", ".join(f"`{c}`" for c in SQL_CORE)
        + ". Native (non-SQL) engines must cover: "
        + ", ".join(f"`{c}`" for c in NATIVE_CORE)
        + ". `async_parity` applies only to engines with an async class. A skipped "
        "check is classified: `verified_limitation` (a probe through the native driver "
        "proved the engine rejects the feature), `declared_unverified` (a declared "
        "limitation with no probe: it blocks `certified` in a core category) or "
        "`environment` (driver/service missing). *Core coverage* is the number of "
        "applicable core categories with a pass or verified limitation.",
        "",
    ]
    live_at = report.get("live_run_at")
    out.append(
        f"Latest recorded live run: **{live_at}**."
        if live_at
        else "No live run recorded."
    )
    out.append("")
    all_live = report.get("live_engines", [])
    live_engines = [e for e in all_live if e["passed"] + e["failed"] + e["xfailed"]]
    not_run = [e["engine"] for e in all_live if e not in live_engines]
    if live_engines:
        out += [
            "### Engines in the latest live run",
            "",
            "| Engine | Version | Passed | Failed | Known issues | Skipped | Core coverage "
            "| Unverified skips | Run | Platform |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
        for e in live_engines:
            version = str(e["version"] or "?").splitlines()[0][:70]
            platform_name = str(e.get("platform") or "?")[:28]
            out.append(
                f"| {e['engine']} | {version} | {e['passed']} | {e['failed']} | "
                f"{e['xfailed']} | {e['skipped']} | {core_label(e.get('depth'))} | "
                f"{_unverified_cell(e.get('depth'))} | {e['run_at']} | {platform_name} |"
            )
        out.append("")
    if not_run:
        out += [
            "Selected but not exercised in that run (engine unreachable, driver "
            f"missing or credentials not set): {', '.join(not_run)}.",
            "",
        ]
    out += [
        "## Connectors",
        "",
        "| Class | Mode | Tier | Install extra | Live run | Core coverage "
        "| Unverified skips | Registered names |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["connectors"]:
        extra = f"`[{r['extra']}]`" if r["extra"] else "none"
        names = ", ".join(f"`{n}`" for n in [r["name"], *r["aliases"]])
        live = r["live"]
        live_cell = "-"
        core_cell = "-"
        unverified_cell = "-"
        if live:
            live_cell = f"{live['engine']} ({live['passed']} pass"
            if live["failed"]:
                live_cell += f", {live['failed']} fail"
            if live["xfailed"]:
                live_cell += f", {live['xfailed']} known"
            live_cell += f", {live.get('skipped') or 0} skip)"
            core_cell = core_label(live.get("depth"))
            unverified_cell = _unverified_cell(live.get("depth"))
        out.append(
            f"| `{r['class']}` | {r['mode']} | {r['tier']} | {extra} | "
            f"{live_cell} | {core_cell} | {unverified_cell} | {names} |"
        )
    out.append("")
    return "\n".join(out)


def run_live_suite(
    engines: list[str] | None = None,
    root: Path | None = None,
    strict: bool = False,
) -> tuple[int, dict[str, Any]]:
    """
    Run ``tests/integration`` (the opt-in live conformance suite) in a subprocess
    and return ``(pytest_exit_code, report)``. Needs a source checkout.
    """
    import os
    import subprocess
    import tempfile

    base = root or repo_root()
    if base is None or not (base / "tests" / "integration").is_dir():
        raise RuntimeError(
            "the live suite needs a source checkout (tests/integration not found)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "live_report.json"
        env = dict(os.environ)
        env["QB_IT_REPORT"] = str(report_path)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(base), env.get("PYTHONPATH", "")])
        )
        if engines:
            env["QB_IT_ENGINES"] = ",".join(engines)
            if strict:
                env["QB_IT_STRICT"] = ",".join(engines)
        elif strict:
            env["QB_IT_STRICT"] = "all"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration",
            "-m",
            "integration",
            "-o",
            "addopts=",
            "-q",
            "-p",
            "no:cacheprovider",
            "--tb=short",
        ]
        proc = subprocess.run(cmd, cwd=base, env=env, check=False)  # noqa: S603
        report: dict[str, Any] = {"run_at": None, "engines": {}}
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
    return proc.returncode, report


def render_live_summary(report: dict[str, Any]) -> str:
    """Per-engine pass/skip/fail table for a live-suite report."""
    rows = [
        (
            "ENGINE",
            "VERSION",
            "PASS",
            "FAIL",
            "KNOWN",
            "SKIP",
            "CORE",
            "UNVERIF",
            "NOTE",
        )
    ]
    for name, rec in sorted(report.get("engines", {}).items()):
        d = depth(rec)
        if rec.get("failed"):
            note = "FAILED"
        elif rec.get("passed"):
            if rec.get("xfailed"):
                note = "known issues"
            elif d is not None and d["meets_bar"]:
                note = "ok (certified depth)"
            else:
                note = "ok (basic depth)"
        else:
            reasons = list(rec.get("skip_reasons", {}))
            note = f"skipped: {reasons[0]}" if reasons else "no tests ran"
        rows.append(
            (
                name,
                str(rec.get("version") or "-").splitlines()[0][:32],
                str(rec.get("passed", 0)),
                str(rec.get("failed", 0)),
                str(rec.get("xfailed", 0)),
                str(rec.get("skipped", 0)),
                f"{len(d['covered'])}/{d['total']}" if d else "-",
                str(len(d["declared_unverified"])) if d else "-",
                note,
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(8)]
    return "\n".join(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:8]))
        + "  "
        + row[8]
        for row in rows
    )


def live_exit_code(returncode: int, report: dict[str, Any]) -> int:
    """Non-zero when an engine failed or the run broke (pytest 5 = nothing collected)."""
    failed = sum(rec.get("failed", 0) for rec in report.get("engines", {}).values())
    return 1 if failed or returncode not in (0, 5) else 0
