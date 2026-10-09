"""
Registry-driven connector matrix (runs in the default suite, needs no services).

For EVERY registered connector class this verifies, without any database or
driver being present:

* the module imports and the class is registered under a primary name;
* its documented ``query-builder-engine[<extra>]`` install extra exists in
  ``pyproject.toml``;
* the third-party driver module(s) it imports lazily are declared (derived
  from its source by ``query_builder.connectors.status``);
* instantiating it does not crash and ``connect()`` raises
  ``DriverNotInstalledError`` (not a random error) when the driver is absent
  (absence is simulated by blocking the declared modules, so the check is the
  same on machines that do have the drivers installed);
* ``dialect_name`` resolves to a *registered* dialect (``get_dialect`` silently
  falls back to postgres for unknown names, so membership is checked directly);
* sync/async parity is reported.

A JSON report is written to ``$QB_MATRIX_REPORT`` (default: pytest tmp dir).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import re
import sys

import pytest

from query_builder.connectors import status
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import DriverNotInstalledError
from query_builder.connectors.registry import ConnectorRegistry
from query_builder.dialects import DIALECTS

RECORDS = status.collect_connectors()
IDS = [r["key"].rsplit(".", 1)[-1] for r in RECORDS]
EXTRAS = status.pyproject_extras()
CLASSES = {}
for _name, _cls in ConnectorRegistry._registry.items():
    if _cls.__module__.startswith("query_builder.connectors."):
        CLASSES[status.class_key(_cls)] = _cls

#: classes that legitimately need no third-party driver
BUILTIN = {"SQLiteConnector", "GenericDBAPIConnector"}


def _cls(rec):
    return CLASSES[rec["key"]]


def test_matrix_is_nonempty_and_counts_are_consistent():
    assert RECORDS
    assert len({r["key"] for r in RECORDS}) == len(RECORDS)
    names = [n for r in RECORDS for n in [r["name"], *r["aliases"]]]
    assert len(names) == len(set(names))
    assert set(names) <= set(ConnectorRegistry._registry)
    assert sum(r["mode"] == "async" for r in RECORDS) == sum(
        issubclass(c, AsyncBaseConnector) for c in CLASSES.values()
    )


@pytest.mark.parametrize("rec", RECORDS, ids=IDS)
def test_class_is_importable_and_registered(rec):
    module = importlib.import_module(rec["module"])
    assert getattr(module, rec["class"]) is _cls(rec)
    assert ConnectorRegistry._registry[rec["name"]] is _cls(rec)


@pytest.mark.parametrize("rec", RECORDS, ids=IDS)
def test_install_extra_exists_in_pyproject(rec):
    if rec["class"] in BUILTIN:
        assert rec["extra"] is None
        return
    assert rec["extra"], f"{rec['class']} documents no install extra"
    assert rec["extra"] in EXTRAS, (
        f"{rec['class']} tells users to install query-builder-engine[{rec['extra']}] "
        "but pyproject.toml has no such optional-dependency group"
    )


@pytest.mark.parametrize("rec", RECORDS, ids=IDS)
def test_driver_modules_are_declared(rec):
    if rec["class"] in BUILTIN:
        assert rec["drivers"] == []
    else:
        assert rec["drivers"], f"{rec['class']} imports no declared driver module"


@pytest.mark.parametrize("rec", RECORDS, ids=IDS)
def test_dialect_name_resolves_to_registered_dialect(rec):
    assert rec["dialect"] in DIALECTS, (
        f"{rec['class']}.dialect_name={rec['dialect']!r} is not a registered dialect "
        "(get_dialect() would silently fall back to postgres)"
    )


@pytest.mark.parametrize("rec", RECORDS, ids=IDS)
def test_missing_driver_raises_driver_not_installed(rec, monkeypatch):
    if rec["class"] in BUILTIN:
        pytest.skip("builtin: no third-party driver")
    for mod in rec["drivers"]:
        monkeypatch.setitem(sys.modules, mod, None)
    instance = _cls(rec)()  # instantiation without a driver must not crash

    async def _connect():
        result = instance.connect()
        if inspect.isawaitable(result):
            result = await result
        return result

    with pytest.raises(DriverNotInstalledError):
        asyncio.run(_connect())


_DIST_ALIASES = {
    "MySQLdb": "mysqlclient",
    "cx_Oracle": "cx-oracle",
    "pyathena": "pyathena",
    "taos": "taospy",
    "taosrest": "taospy",
    "impala": "impyla",
    "impyla": "impyla",
    "hive": "pyhive",
    "pyhive": "pyhive",
    "ibm_db_dbi": "ibm-db",
    "firebird": "firebird-driver",
    "fdb": "firebird-driver",
    "cassandra": "cassandra-driver|scylla-driver",
    "arango": "python-arango",
    "azure": "azure",
    "google": "google-cloud",
    "databricks": "databricks-sql-connector",
    "snowflake": "snowflake-connector-python",
    "firebolt": "firebolt-sdk",
    "weaviate": "weaviate-client",
    "pinecone": "pinecone-client",
    "qdrant_client": "qdrant-client",
    "influxdb3_python": "influxdb3-python",
    "influxdb3_client": "influxdb3-python",
    "vertica_python": "vertica-python",
    "redshift_connector": "redshift-connector",
    "clickhouse_connect": "clickhouse-connect",
    "clickhouse_driver": "clickhouse-driver",
    "opensearchpy": "opensearch-py",
    "opensearch_py": "opensearch-py",
    "prometheus_api_client": "prometheus-api-client",
    "pyarrow": "pyarrow",
    "pydrill": "pydrill",
    "pydruid": "pydruid",
    "pinotdb": "pinotdb",
    "pykx": "pykx",
    "crate": "crate",
    "hdbcli": "hdbcli",
    "pyspark": "pyspark",
    "kyuubi": "pyhive",
    # the `prestodb` module ships in the `presto-python-client` distribution
    "prestodb": "presto-python-client",
}

#: Known gaps between a class's driver modules and its install extra, found by
#: this matrix. They are REPORTED (see the JSON report) rather than fixed here
#: because pyproject.toml is owned by the release/supply-chain work. Remove an
#: entry once the extra is fixed; the test fails on any NEW mismatch.
KNOWN_EXTRA_GAPS: set[str] = {
    # extra `derby` installs pydrill, but Derby needs jaydebeapi (JDBC) or drda.
    "DerbyConnector",
    "AsyncDerbyConnector",
}


def _extra_requirements(extra: str, _seen: frozenset[str] = frozenset()) -> list[str]:
    """Distribution names an extra installs, following self-referencing alias extras
    (``query-builder-engine[postgresql]``) to the extra they point at."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
    )
    project = data["project"]
    own_name = project["name"].lower().replace("_", "-")
    out: list[str] = []
    for req in project["optional-dependencies"][extra]:
        name = re.split(r"[\[<>=!~; ]", req, maxsplit=1)[0].lower()
        if name.replace("_", "-") == own_name:
            for target in re.findall(r"\[([^\]]*)\]", req):
                for sub in (t.strip() for t in target.split(",")):
                    if sub and sub not in _seen:
                        out.extend(_extra_requirements(sub, _seen | {extra}))
        else:
            out.append(name)
    return out


def extra_provides_driver(rec) -> bool | None:
    if not rec["extra"] or not rec["drivers"]:
        return None
    reqs = _extra_requirements(rec["extra"])
    for mod in rec["drivers"]:
        root = mod.split(".")[0]
        for want in _DIST_ALIASES.get(root, root).lower().replace("_", "-").split("|"):
            if any(want == r or want in r or r in want for r in reqs):
                return True
    return False


def test_report_and_extra_driver_consistency(tmp_path_factory):
    rows, gaps, parity = [], [], []
    for rec in RECORDS:
        ok = extra_provides_driver(rec)
        rows.append({**rec, "extra_provides_driver": ok})
        if ok is False:
            gaps.append(rec["class"])
    sync_only = sorted(
        r["class"] for r in RECORDS if r["mode"] == "sync" and not r["counterpart"]
    )
    async_only = sorted(
        r["class"] for r in RECORDS if r["mode"] == "async" and not r["counterpart"]
    )
    parity = {"sync_without_async": sync_only, "async_without_sync": async_only}
    report = {
        "totals": {
            "classes": len(RECORDS),
            "registered_names": sum(1 + len(r["aliases"]) for r in RECORDS),
            "sync": sum(r["mode"] == "sync" for r in RECORDS),
            "async": sum(r["mode"] == "async" for r in RECORDS),
        },
        "extra_does_not_provide_driver": sorted(gaps),
        "parity": parity,
        "connectors": rows,
    }
    out = os.environ.get("QB_MATRIX_REPORT") or str(
        tmp_path_factory.mktemp("matrix") / "connector_matrix_report.json"
    )
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    assert not parity["async_without_sync"]
    assert set(gaps) <= KNOWN_EXTRA_GAPS, (
        "install extra does not contain the driver the class imports: "
        f"{sorted(set(gaps) - KNOWN_EXTRA_GAPS)}"
    )
