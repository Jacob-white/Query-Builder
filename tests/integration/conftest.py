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
* a JSON report (per-engine passed/failed/skipped, engine version) is written
  to ``$QB_IT_REPORT`` (default ``tests/integration/.reports/latest.json``).
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

from tests.integration import engines as eng

REPORT_DEFAULT = Path(__file__).parent / ".reports" / "latest.json"

_RESULTS: dict[str, dict[str, Any]] = collections.defaultdict(
    lambda: {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "skip_reasons": collections.Counter(),
        "failures": [],
    }
)
_VERSIONS: dict[str, str] = {}
_PARAM_NAMES = ("engine_name", "smoke_engine_name", "async_engine_name")


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "qb_engine(name): attribute a test to an engine in the live report"
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


def _strict(name: str) -> bool:
    raw = os.environ.get("QB_IT_STRICT", "").lower()
    return raw == "all" or name in [p.strip() for p in raw.split(",") if p.strip()]


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
    except eng.EngineUnavailable as exc:
        outcome: BaseException = eng.EngineUnavailable(str(exc))
        _LIVE_CACHE[name] = outcome
        raise outcome from exc
    conn = engine.make_connector()
    try:
        info = conn.test_connection()
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
        pytest.skip(str(exc))


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
            if p in callspec.params:
                name = callspec.params[p]
    marker = item.get_closest_marker("qb_engine")
    if marker is not None:
        name = marker.args[0]
    report.qb_engine = name


def pytest_runtest_logreport(report: Any) -> None:
    name = getattr(report, "qb_engine", None)
    if name is None:
        return
    rec = _RESULTS[name]
    if report.when == "call" and report.passed:
        rec["passed"] += 1
    elif report.failed:
        rec["failed"] += 1
        rec["failures"].append(report.nodeid)
    elif report.skipped:
        rec["skipped"] += 1
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else "skipped"
        rec["skip_reasons"][reason.removeprefix("Skipped: ")] += 1


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    if not _RESULTS:
        return
    engines_out: dict[str, Any] = {}
    for name, rec in sorted(_RESULTS.items()):
        e = eng.ENGINES.get(name)
        engines_out[name] = {
            "connectors": e.connector_class_keys() if e else [],
            "tier": e.tier if e else "cloud",
            "version": _VERSIONS.get(name),
            "passed": rec["passed"],
            "failed": rec["failed"],
            "skipped": rec["skipped"],
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


def pytest_unconfigure(config: Any) -> None:
    for live_obj in list(_LIVE_CACHE.values()):
        if isinstance(live_obj, Live) and os.environ.get("QB_IT_KEEP_DATA") != "1":
            try:
                live_obj.engine.cleanup()
            except Exception:  # noqa: BLE001
                pass
