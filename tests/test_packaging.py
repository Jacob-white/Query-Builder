"""Packaging invariants: version single-sourcing, extras hygiene, entry points."""

from __future__ import annotations

import io
import json
import re
import tomllib
from pathlib import Path

import query_builder
from query_builder import mcp_server

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
EXTRAS = PYPROJECT["project"]["optional-dependencies"]
SELF = "query-builder-engine"

# Drivers that need a compiler, vendor client library, JVM or are very large. They must
# never leak into `all`, which has to install on every supported platform.
NATIVE_ONLY = {
    "mysqlclient",
    "pymssql",
    "pyodbc",
    "ibm-db",
    "hdbcli",
    "teradatasql",
    "pykx",
    "chdb",
    "taospy",
    "pyspark",
    "couchbase",
    "pyhive",
    "impyla",
    "pyoceanbase",
    "jaydebeapi",
}


def _dist_name(requirement: str) -> str:
    return re.split(r"[\[<>=!~ ;]", requirement, maxsplit=1)[0].lower()


def _refs(requirement: str) -> list[str]:
    match = re.fullmatch(rf"{SELF}\[(.+)\]", requirement)
    return match.group(1).split(",") if match else []


def _expand(extra: str, seen: frozenset[str] = frozenset()) -> set[str]:
    assert extra not in seen, f"cyclic extra reference: {extra}"
    names: set[str] = set()
    for req in EXTRAS[extra]:
        refs = _refs(req)
        if refs:
            for ref in refs:
                names |= _expand(ref, seen | {extra})
        else:
            names.add(_dist_name(req))
    return names


def test_version_is_single_sourced():
    assert "version" in PYPROJECT["project"]["dynamic"]
    assert "version" not in PYPROJECT["project"]
    assert PYPROJECT["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "query_builder.__version__"
    }
    assert re.fullmatch(r"\d+\.\d+\.\d+([abrc.\w-]*)?", query_builder.__version__)


def test_py_typed_marker_ships():
    assert (ROOT / "query_builder" / "py.typed").is_file()
    assert PYPROJECT["tool"]["setuptools"]["package-data"]["query_builder"] == [
        "py.typed"
    ]


def test_not_marked_production_stable():
    classifiers = PYPROJECT["project"]["classifiers"]
    assert "Development Status :: 4 - Beta" in classifiers
    assert not any("Production/Stable" in c for c in classifiers)


def test_self_references_resolve_and_are_acyclic():
    for extra, reqs in EXTRAS.items():
        for req in reqs:
            for ref in _refs(req):
                assert ref in EXTRAS, f"{extra} references unknown extra {ref}"
        _expand(extra)


def test_extras_have_no_duplicate_requirements():
    for extra, reqs in EXTRAS.items():
        names = [_dist_name(r) for r in reqs]
        assert len(names) == len(set(names)), f"duplicate entries in extra {extra}"


def test_all_excludes_native_drivers_and_all_native_includes_them():
    assert not (_expand("all") & NATIVE_ONLY)
    assert NATIVE_ONLY <= _expand("all-native")
    assert _expand("all") <= _expand("all-native")


def test_required_extras_exist():
    for name in ("server", "django", "sql", "cloud-warehouses", "nosql", "vector"):
        assert name in EXTRAS
    assert {"fastapi", "starlette", "uvicorn"} <= _expand("server")
    assert {"django", "djangorestframework", "django-ninja"} <= _expand("django")
    # h2/derby are JDBC databases: they must not map to PostgreSQL/Drill drivers.
    assert _expand("h2") == {"jaydebeapi"}
    assert _expand("derby") == {"jaydebeapi"}


def test_console_scripts_target_real_callables():
    scripts = PYPROJECT["project"]["scripts"]
    assert scripts["query-builder"] == "query_builder.cli:main"
    assert scripts["query-builder-mcp"] == "query_builder.mcp_server:main"
    assert callable(mcp_server.main)


def test_mcp_main_serves_stdio(monkeypatch, capsys):
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    monkeypatch.setattr("sys.stdin", io.StringIO(request + "\n"))
    assert mcp_server.main() == 0
    assert json.loads(capsys.readouterr().out)["result"] == {}
