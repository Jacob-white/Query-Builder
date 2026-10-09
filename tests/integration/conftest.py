"""
Pytest wiring for the live integration suite.

* every test under ``tests/integration`` is auto-marked ``integration`` (the
  default run deselects the marker, see ``[tool.pytest.ini_options]``);
* ``engine_name`` / ``smoke_engine_name`` fixtures parametrize a test over all
  engines (``QB_IT_ENGINES=postgres,mysql`` narrows it);
* the ``live`` fixture checks reachability + driver availability, seeds the
  standard dataset once per engine, and SKIPS with a precise reason when the
  engine cannot run here (set ``QB_IT_STRICT=postgres,mysql`` or ``all`` to turn
  those skips into failures, e.g. in CI);
* a JSON report (per-engine passed/failed/skipped, engine version, and per-CATEGORY
  evidence: passed/failed/xfailed and skips classified as ``verified_limitation``,
  ``declared_unverified`` or ``environment``) is written to ``$QB_IT_REPORT`` (default
  ``tests/integration/.reports/latest.json``). ``query_builder/connectors/status.py`` turns
  that evidence into tiers.
"""

from __future__ import annotations

import collections
import datetime
import json
import os
import platform
from pathlib import Path
from typing import Any

import pytest

from tests.integration import categories as cat
from tests.integration import engines as eng

REPORT_DEFAULT = Path(__file__).parent / ".reports" / "latest.json"

_RESULTS: dict[str, dict[str, Any]] = collections.defaultdict(
    lambda: {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "known_issues": [],
        "skip_reasons": collections.Counter(),
        "failures": [],
        "cats": collections.defaultdict(cat.empty_category),
        "skips": [],  # (category, kind, feature) classified at session finish
    }
)
_VERSIONS: dict[str, str] = {}
#: (engine, feature) -> True when the probe confirmed the engine REJECTS the feature
_PROBES: dict[tuple[str, str], bool] = {}
_PARAM_NAMES = (
    "engine_name",
    "smoke_engine_name",
    "async_engine_name",
    "limitation_id",
)


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "qb_engine(name): attribute a test to an engine in the live report"
    )
    config.addinivalue_line(
        "markers",
        "qb_category(name): attribute a test to a check category (tests/integration/"
        "categories.py) in the live report",
    )


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    here = str(Path(__file__).parent)
    for item in items:
        if str(item.fspath).startswith(here):
            item.add_marker(pytest.mark.integration)


def _names(kind: str) -> list[str]:
    names = eng.selected_engine_names()
    if kind == "engine_name":
        return [n for n in names if eng.ENGINES[n].family]
    if kind == "smoke_engine_name":
        from tests.integration import smoke

        return [n for n in names if n in smoke.SMOKE]
    if kind == "limitation_id":
        from tests.integration import limits

        return [i for i in limits.probe_ids() if i.split("::")[0] in names]
    from tests.integration import async_engines

    return [n for n in names if n in async_engines.ASYNC]


def pytest_generate_tests(metafunc: Any) -> None:
    for kind in _PARAM_NAMES:
        if kind in metafunc.fixturenames:
            metafunc.parametrize(kind, _names(kind), ids=str, indirect=True)


@pytest.fixture
def engine_name(request: Any) -> str:
    return request.param


@pytest.fixture
def smoke_engine_name(request: Any) -> str:
    return request.param


@pytest.fixture
def async_engine_name(request: Any) -> str:
    return request.param


@pytest.fixture
def limitation_id(request: Any) -> str:
    return request.param


def _strict(name: str) -> bool:
    raw = os.environ.get("QB_IT_STRICT", "").lower()
    return raw == "all" or name in [p.strip() for p in raw.split(",") if p.strip()]


def record_version(name: str, version: str) -> None:
    """Remember an engine's reported version for the run report."""
    _VERSIONS[name] = version.replace("\n", " ")[:120]


class Live:
    """A seeded, reachable engine."""

    def __init__(self, engine: eng.Engine, version: str) -> None:
        self.engine = engine
        self.version = version


_LIVE_CACHE: dict[str, Live | BaseException] = {}


def _ensure_live(name: str) -> Live:
    cached = _LIVE_CACHE.get(name)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached
    engine = eng.ENGINES[name]
    try:
        engine.check_available()
        if engine.family:
            engine.seed()
        else:
            from tests.integration import smoke

            if name in smoke.SMOKE:
                smoke.SMOKE[name].seed(engine)
                if smoke.SMOKE[name].extra_seed is not None:
                    smoke.SMOKE[name].extra_seed(engine)
    except eng.EngineUnavailable as exc:
        outcome: BaseException = eng.EngineUnavailable(str(exc))
        _LIVE_CACHE[name] = outcome
        raise outcome from exc
    except Exception as exc:
        # Seeding with the vendor driver failed: a harness/environment problem,
        # reported once per engine rather than once per test.
        failure = RuntimeError(f"{name}: seeding failed: {exc}")
        _LIVE_CACHE[name] = failure
        raise failure from exc
    conn = engine.make_connector()
    try:
        info = conn.test_connection()
    except Exception as exc:
        failure = RuntimeError(
            f"{name}: connector.test_connection() failed: {type(exc).__name__}: {exc}"
        )
        _LIVE_CACHE[name] = failure
        raise failure from exc
    finally:
        conn.close()
    version = str(info.get("engine_version") or "?").replace("\n", " ")[:120]
    _VERSIONS[name] = version
    live = Live(engine, version)
    _LIVE_CACHE[name] = live
    return live


def _live_or_skip(name: str) -> Live:
    try:
        return _ensure_live(name)
    except eng.EngineUnavailable as exc:
        if _strict(name):
            pytest.fail(f"[strict] {name} required but unavailable: {exc}")
        pytest.skip(cat.environment_reason(str(exc)))


@pytest.fixture
def engine(engine_name: str) -> eng.Engine:
    return _live_or_skip(engine_name).engine


@pytest.fixture
def smoke_engine(smoke_engine_name: str) -> eng.Engine:
    return _live_or_skip(smoke_engine_name).engine


@pytest.fixture
def async_engine(async_engine_name: str) -> eng.Engine:
    return _live_or_skip(async_engine_name).engine


@pytest.fixture
def limitation_engine(limitation_id: str) -> eng.Engine:
    return _live_or_skip(limitation_id.split("::")[0]).engine


@pytest.fixture
def conn(engine: eng.Engine) -> Any:
    connector = engine.make_connector()
    connector.connect()
    try:
        yield connector
    finally:
        connector.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Any, call: Any) -> Any:
    outcome = yield
    report = outcome.get_result()
    name = None
    callspec = getattr(item, "callspec", None)
    if callspec is not None:
        for p in _PARAM_NAMES:
            value = callspec.params.get(p)
            if isinstance(value, str):  # NOTSET for an empty engine selection
                name = value.split("::")[0]
    marker = item.get_closest_marker("qb_engine")
    if marker is not None:
        name = marker.args[0]
    report.qb_engine = name
    report.qb_category = cat.category_of(item)


def pytest_runtest_logreport(report: Any) -> None:
    name = getattr(report, "qb_engine", None)
    if name is None:
        return
    rec = _RESULTS[name]
    category = getattr(report, "qb_category", "uncategorized")
    crec = rec["cats"][category]
    if report.when == "call" and report.passed:
        rec["passed"] += 1
        crec["passed"] += 1
    elif report.failed:
        rec["failed"] += 1
        crec["failed"] += 1
        rec["failures"].append(report.nodeid)
    elif report.skipped and hasattr(report, "wasxfail"):
        rec["xfailed"] += 1
        crec["xfailed"] += 1
        rec["known_issues"].append(f"{report.nodeid}: {report.wasxfail}")
    elif report.skipped:
        rec["skipped"] += 1
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else "skipped"
        reason = reason.removeprefix("Skipped: ")
        rec["skip_reasons"][reason] += 1
        kind, feature = cat.classify_skip(reason)
        rec["skips"].append((category, kind, feature))


def _category_counts(value: dict[str, Any]) -> dict[str, Any]:
    out = cat.empty_category()
    out.update({k: value[k] for k in ("passed", "failed", "xfailed")})
    return out


def classify_skips(name: str, rec: dict[str, Any]) -> dict[str, Any]:
    """Per-category evidence for one engine, with every skip classified.

    * ``verified_limitation``: a declared limitation whose probe ran in this session and
      confirmed the engine rejects the feature;
    * ``declared_unverified``: a declared limitation without a probe (or whose probe did
      not run), and any skip with no declared reason (an UNTESTED check);
    * ``environment``: driver/service/credentials missing.
    """
    from tests.integration import limits

    categories: dict[str, Any] = {
        k: _category_counts(v) for k, v in rec["cats"].items()
    }
    verified: set[str] = set()
    unverified: set[str] = set()
    for category, kind, feature in rec["skips"]:
        skipped = categories.setdefault(category, cat.empty_category())["skipped"]
        if kind == "environment":
            skipped["environment"] += 1
        elif kind == "limitation" and feature is not None:
            lim = limits.lookup(name, feature)
            if (
                lim is not None
                and lim.probe is not None
                and _PROBES.get((name, feature))
            ):
                skipped["verified_limitation"] += 1
                verified.add(feature)
            else:
                skipped["declared_unverified"] += 1
                unverified.add(feature)
        else:
            skipped["declared_unverified"] += 1
    return {
        "categories": categories,
        "limitations": {
            "verified": sorted(verified),
            "declared_unverified": sorted(unverified - verified),
        },
    }


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    if not _RESULTS:
        return
    engines_out: dict[str, Any] = {}
    for name, rec in sorted(_RESULTS.items()):
        e = eng.ENGINES.get(name)
        c = None
        if e is None:
            from tests.integration import cloud

            c = cloud.CLOUD.get(name)
        evidence = classify_skips(name, rec)
        has_async = bool(e and e.async_connector)
        kind = "sql" if (e is None or e.family) else "native"
        engines_out[name] = {
            "family_kind": kind,
            "core": cat.core_for(kind, has_async),
            "categories": evidence["categories"],
            "limitations": evidence["limitations"],
            "connectors": (e or c).connector_class_keys() if (e or c) else [],
            "tier": e.tier if e else "cloud",
            "emulated": bool(e and e.emulated),
            "version": _VERSIONS.get(name),
            "passed": rec["passed"],
            "failed": rec["failed"],
            "skipped": rec["skipped"],
            "xfailed": rec["xfailed"],
            "known_issues": rec["known_issues"],
            "skip_reasons": dict(rec["skip_reasons"]),
            "failures": rec["failures"],
        }
    out = {
        "run_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "engines": engines_out,
    }
    path = Path(os.environ.get("QB_IT_REPORT") or REPORT_DEFAULT)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:  # e.g. read-only checkout: never fail the run for this
        print(f"\n[integration] could not write report {path}: {exc}")


def pytest_unconfigure(config: Any) -> None:
    for live_obj in list(_LIVE_CACHE.values()):
        if isinstance(live_obj, Live) and os.environ.get("QB_IT_KEEP_DATA") != "1":
            try:
                live_obj.engine.cleanup()
            except Exception:  # noqa: BLE001
                pass
