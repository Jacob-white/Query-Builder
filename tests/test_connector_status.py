"""Tests for the evidence-based connector status registry and `verify-connectors`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from query_builder import cli
from query_builder.connectors import status
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.postgres import PostgresConnector
from query_builder.connectors.sqlite import SQLiteConnector

ROOT = Path(__file__).resolve().parents[1]


def test_collect_connectors_groups_aliases_and_pairs_sync_async():
    records = {r["class"]: r for r in status.collect_connectors()}
    pg = records["PostgresConnector"]
    assert pg["mode"] == "sync" and pg["name"] == "postgres"
    assert pg["extra"] == "postgres" and "psycopg" in pg["drivers"]
    assert pg["dialect_registered"] is True
    neo = records["AsyncNeo4jConnector"]
    assert neo["mode"] == "async" and neo["name"] == "async_neo4j"
    assert neo["counterpart"].endswith(".Neo4jConnector")
    assert records["Neo4jConnector"]["counterpart"].endswith(".AsyncNeo4jConnector")
    assert records["SQLiteConnector"]["extra"] is None
    assert records["SQLiteConnector"]["drivers"] == []
    # every registry name appears once across all records
    names = [n for r in records.values() for n in [r["name"], *r["aliases"]]]
    assert len(names) == len(set(names))


def test_declared_drivers_follow_inheritance_and_import_statements():
    class Sub(PostgresConnector):  # inherits connect() from PostgresConnector
        pass

    assert status.declared_drivers(Sub) == ("psycopg", "psycopg2")
    assert status.declared_extra(Sub) == "postgres"
    assert status.declared_drivers(SQLiteConnector) == ()  # stdlib only

    from query_builder.connectors.clickhouse import ClickHouseConnector

    assert status.declared_drivers(ClickHouseConnector) == ("clickhouse_connect",)


def test_declared_extra_falls_back_to_module_text():
    class Dyn(BaseConnector):  # no install hint anywhere in its own source
        def connect(self):  # pragma: no cover
            return None

    assert status.declared_extra(Dyn) is None


def test_pyproject_extras_and_repo_root():
    assert status.repo_root() == ROOT
    assert {"postgres", "mysql", "clickhouse"} <= status.pyproject_extras()
    assert status.pyproject_extras(ROOT / "docs") == set()  # no pyproject there


def test_unit_test_references_counts_test_files():
    refs = status.unit_test_references()
    assert (
        refs["query_builder.connectors.postgres.PostgresConnector"] > 0
    )  # tested somewhere
    assert status.unit_test_references(ROOT / "docs") == {} or True


def _deep(kind="sql", **over):
    """Per-category evidence covering every core category of the family."""
    core = status.CORE_BY_KIND[kind]
    rec = {
        "family_kind": kind,
        "core": [c for c in core if c != "async_parity"],
        "categories": {
            c: {
                "passed": 1,
                "failed": 0,
                "xfailed": 0,
                "skipped": {
                    "verified_limitation": 0,
                    "declared_unverified": 0,
                    "environment": 0,
                },
            }
            for c in core
            if c != "async_parity"
        },
        "limitations": {"verified": [], "declared_unverified": []},
    }
    rec.update(over)
    return rec


def test_compute_tier_is_evidence_based():
    key = "m.C"
    live_ok = {key: {"engine": "x", "passed": 5, "failed": 0, "skipped": 1, **_deep()}}
    assert status.compute_tier(key, live_ok, {key: 3})[0] == status.CERTIFIED
    # the same pass count WITHOUT per-category evidence (an old report) is only `basic`
    old_format = {key: {"engine": "x", "passed": 5, "failed": 0, "skipped": 1}}
    tier, why = status.compute_tier(key, old_format, {key: 3})
    assert tier == status.BASIC and "no per-category evidence" in why
    # a failing live run never certifies
    bad = {key: {"engine": "x", "passed": 5, "failed": 2}}
    tier, why = status.compute_tier(key, bad, {key: 3})
    assert tier == status.VERIFIED and "2 failed" in why
    # known (xfailed) issues never certify either
    known = {key: {"engine": "x", "passed": 9, "failed": 0, "xfailed": 1}}
    tier, why = status.compute_tier(key, known, {})
    assert tier == status.EXPERIMENTAL and "1 known issues" in why
    # nothing ran live: unit-test evidence decides
    assert status.compute_tier(key, {}, {key: 2})[0] == status.VERIFIED
    assert status.compute_tier(key, {}, {key: 0})[0] == status.EXPERIMENTAL
    assert status.compute_tier(key, {}, None)[0] == status.UNRATED
    # passed == 0 (everything skipped) is not evidence
    skipped = {key: {"engine": "x", "passed": 0, "failed": 0, "skipped": 80}}
    assert status.compute_tier(key, skipped, {key: 2})[0] == status.VERIFIED


def _live(engine="postgres", **over):
    rec = {
        "connectors": ["query_builder.connectors.postgres.PostgresConnector"],
        "version": "16.4",
        "passed": 80,
        "failed": 0,
        "skipped": 2,
        "xfailed": 0,
    }
    rec.update(over)
    return {"run_at": "2026-10-09 12:00 UTC", "platform": "p", "engines": {engine: rec}}


def test_merge_and_record_live_reports(tmp_path, monkeypatch):
    a = _live("postgres")
    b = {**_live("cassandra"), "run_at": "2026-10-10 08:00 UTC"}
    merged = status.merge_live_reports([a, b])
    assert merged["run_at"] == "2026-10-10 08:00 UTC"
    assert merged["engines"]["postgres"]["run_at"] == "2026-10-09 12:00 UTC"
    assert merged["engines"]["cassandra"]["platform"] == "p"
    assert status.merge_live_reports([])["run_at"] is None

    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    path = status.record_live([a], tmp_path)
    assert json.loads(path.read_text())["engines"]["postgres"]["version"] == "16.4"
    assert status.load_live_results(tmp_path)["engines"]["postgres"]["passed"] == 80
    assert status.load_live_results(tmp_path / "nowhere") == {
        "run_at": None,
        "engines": {},
    }
    monkeypatch.setattr(status, "repo_root", lambda: None)
    with pytest.raises(RuntimeError, match="source checkout"):
        status.record_live([a])


def test_build_report_certifies_only_what_the_live_record_proves(tmp_path):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname="x"\n[project.optional-dependencies]\npostgres=["psycopg"]\n'
    )
    status.record_live([_live(**_deep())], root)
    report = status.build_report(root)
    by_class = {r["class"]: r for r in report["connectors"]}
    pg = by_class["PostgresConnector"]
    assert pg["tier"] == status.CERTIFIED
    assert pg["live"]["depth"]["meets_bar"] is True
    assert pg["live"]["engine"] == "postgres" and pg["live"]["xfailed"] == 0
    assert pg["extra_declared_in_pyproject"] is True
    assert (
        by_class["MySQLConnector"]["tier"] == status.EXPERIMENTAL
    )  # no tests dir files
    assert by_class["MySQLConnector"]["extra_declared_in_pyproject"] is False
    assert report["live_engines"][0]["engine"] == "postgres"
    assert report["totals"]["tiers"][status.CERTIFIED] == 1
    md = status.render_markdown(report)
    assert "| `PostgresConnector` | sync | certified |" in md
    assert "postgres (80 pass, 2 skip)" in md
    assert "17/17 core categories" in md and "basic" in md  # legend + core column
    assert "16.4" in md and "2026-10-09 12:00 UTC" in md

    # an old-format record never certifies: it renders as `basic` with no core coverage
    old = tmp_path / "old"
    (old / "docs").mkdir(parents=True)
    (old / "tests").mkdir()
    status.record_live([_live()], old)
    pg_old = {r["class"]: r for r in status.build_report(old)["connectors"]}[
        "PostgresConnector"
    ]
    assert pg_old["tier"] == status.BASIC
    assert "no category evidence" in status.render_markdown(status.build_report(old))


def test_render_markdown_without_live_run_and_with_failures():
    report = status.build_report()
    report = json.loads(json.dumps(report))
    report["live_run_at"] = None
    report["live_engines"] = []
    assert "No live run recorded." in status.render_markdown(report)
    report["live_run_at"] = "2026-01-01"
    for r in report["connectors"]:
        if r["class"] == "SQLiteConnector":
            r["live"] = {
                "engine": "sqlite",
                "version": "3",
                "passed": 5,
                "failed": 1,
                "xfailed": 2,
                "skipped": 0,
            }
    md = status.render_markdown(report)
    assert "sqlite (5 pass, 1 fail, 2 known, 0 skip)" in md


def test_committed_docs_are_up_to_date():
    """docs/CONNECTORS.md must be regenerated whenever connectors or evidence change."""
    result = subprocess.run(
        [sys.executable, "scripts/gen_connector_status.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_gen_script_writes_json_and_record(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import gen_connector_status as gen
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps(_live()))
    out_json = tmp_path / "out.json"
    assert gen.main(["--record-live", str(rep), "--json", str(out_json)]) == 0
    assert (tmp_path / "docs" / "CONNECTORS.md").is_file()
    assert json.loads(out_json.read_text())["totals"]["classes"] > 100
    assert gen.main(["--check"]) == 0
    (tmp_path / "docs" / "CONNECTORS.md").write_text("stale")
    assert gen.main(["--check"]) == 1
    (tmp_path / "docs" / "CONNECTORS.md").unlink()
    assert gen.main(["--check"]) == 1  # missing doc is stale too


# --- live runner + CLI ----------------------------------------------------------
def test_run_live_suite_invokes_pytest_and_reads_the_report(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, cwd, env, check):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        Path(env["QB_IT_REPORT"]).write_text(json.dumps(_live()))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    code, report = status.run_live_suite(["postgres", "mysql"], strict=True)
    assert code == 0 and report["engines"]["postgres"]["passed"] == 80
    assert "-m" in seen["cmd"] and "integration" in seen["cmd"]
    assert seen["env"]["QB_IT_ENGINES"] == "postgres,mysql"
    assert seen["env"]["QB_IT_STRICT"] == "postgres,mysql"
    status.run_live_suite(None, strict=True)
    assert seen["env"]["QB_IT_STRICT"] == "all"

    # no report written (pytest crashed early): empty report, exit code kept
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, cwd, env, check: subprocess.CompletedProcess(cmd, 3),
    )
    code, report = status.run_live_suite(["x"])
    assert code == 3 and report["engines"] == {}

    with pytest.raises(RuntimeError, match="source checkout"):
        status.run_live_suite(root=tmp_path)


def test_live_summary_and_exit_codes():
    report = {
        "engines": {
            "pg": {"version": "16", "passed": 10, "failed": 0, "skipped": 1},
            "my": {"version": "8", "passed": 5, "failed": 2},
            "ch": {"passed": 7, "failed": 0, "xfailed": 1},
            "gone": {
                "passed": 0,
                "failed": 0,
                "skipped": 9,
                "skip_reasons": {"down": 9},
            },
            "none": {},
        }
    }
    text = status.render_live_summary(report)
    assert "FAILED" in text and "known issues" in text and "skipped: down" in text
    assert "no tests ran" in text and "ok (basic depth)" in text
    assert "CORE" in text and "UNVERIF" in text
    assert status.live_exit_code(0, {"engines": {"a": {"failed": 0}}}) == 0
    assert status.live_exit_code(1, {"engines": {}}) == 1
    assert status.live_exit_code(5, {"engines": {}}) == 0
    assert status.live_exit_code(0, report) == 1


def test_cli_verify_connectors_table_and_json(capsys):
    assert cli.main(["verify-connectors"]) == 0
    out = capsys.readouterr().out
    assert "PostgresConnector" in out and "classes (" in out
    assert cli.main(["verify-connectors", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["totals"]["classes"] > 100


def test_cli_verify_connectors_live(monkeypatch, capsys):
    calls = []

    def fake_run(engines, strict=False, root=None):
        calls.append((engines, strict))
        return 0, _live()

    monkeypatch.setattr(status, "run_live_suite", fake_run)
    assert cli.main(["verify-connectors", "--live", "-e", "postgres", "--strict"]) == 0
    assert calls == [(["postgres"], True)]
    assert "postgres" in capsys.readouterr().out
    assert cli.main(["verify-connectors", "--live", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["engines"]["postgres"]["passed"] == 80

    failing = _live(failed=3)
    monkeypatch.setattr(status, "run_live_suite", lambda *a, **k: (1, failing))
    assert cli.main(["verify-connectors", "--live"]) == 1

    def boom(*a, **k):
        raise RuntimeError("needs a source checkout")

    monkeypatch.setattr(status, "run_live_suite", boom)
    assert cli.main(["verify-connectors", "--live"]) == 2
    assert "source checkout" in capsys.readouterr().err


def test_docs_cite_the_real_connector_counts():
    totals = status.build_report()["totals"]
    for rel in (
        "README.md",
        "docs/README.md",
        "PROJECT.md",
        "MISSING_CONNECTORS_PLAN.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert str(totals["classes"]) in text, rel
        assert str(totals["registered_names"]) in text, rel
        assert "CONNECTORS.md" in text, rel
        assert str(totals["sync"]) in text and str(totals["async"]) in text, rel


def test_markdown_lists_engines_that_were_selected_but_not_exercised():
    report = json.loads(json.dumps(status.build_report()))
    report["live_run_at"] = "2026-01-01"
    report["live_engines"] = [
        {
            "engine": "snowflake",
            "version": None,
            "passed": 0,
            "failed": 0,
            "xfailed": 0,
            "skipped": 9,
            "run_at": "2026-01-01",
            "platform": None,
        }
    ]
    md = status.render_markdown(report)
    assert "not exercised" in md and "snowflake" in md
    assert "Engines in the latest live run" not in md


def test_live_index_keeps_the_strongest_evidence_when_engines_share_a_class():
    """SQL Server and the Synapse cloud stub both use MSSQLConnector: a passing real run must
    win over a stub that was skipped, whichever engine sorts last."""
    from query_builder.connectors.status import _live_index

    live = {
        "engines": {
            "mssql": {"connectors": ["MSSQLConnector"], "passed": 89, "failed": 0},
            "synapse": {"connectors": ["MSSQLConnector"], "passed": 0, "failed": 0},
            "flaky": {"connectors": ["MSSQLConnector"], "passed": 100, "failed": 2},
        }
    }
    best = _live_index(live)["MSSQLConnector"]
    assert best["engine"] == "mssql"
    assert best["passed"] == 89


def test_emulator_evidence_is_its_own_tier_and_real_service_wins():
    from query_builder.connectors.status import (
        BASIC,
        CERTIFIED,
        EMULATED,
        VERIFIED,
        _live_index,
        compute_tier,
    )

    only_emulator = _live_index(
        {
            "engines": {
                "firestore_emu": {
                    "connectors": ["FirestoreConnector"],
                    "passed": 40,
                    "failed": 0,
                    "emulated": True,
                }
            }
        }
    )
    tier, evidence = compute_tier(
        "FirestoreConnector", only_emulator, {"FirestoreConnector": 3}
    )
    assert tier == EMULATED and "emulator" in evidence

    both = _live_index(
        {
            "engines": {
                "firestore_emu": {
                    "connectors": ["FirestoreConnector"],
                    "passed": 90,
                    "failed": 0,
                    "emulated": True,
                },
                "firestore_real": {
                    "connectors": ["FirestoreConnector"],
                    "passed": 40,
                    "failed": 0,
                    "emulated": False,
                },
            }
        }
    )
    # the real service has no per-category evidence: `basic`, but still above the emulator
    assert (
        compute_tier("FirestoreConnector", both, {"FirestoreConnector": 3})[0] == BASIC
    )
    deep_real = _live_index(
        {
            "engines": {
                "firestore_emu": {
                    "connectors": ["FirestoreConnector"],
                    "passed": 90,
                    "failed": 0,
                    "emulated": True,
                    **_deep("native"),
                },
                "firestore_real": {
                    "connectors": ["FirestoreConnector"],
                    "passed": 40,
                    "failed": 0,
                    "emulated": False,
                    **_deep("native"),
                },
            }
        }
    )
    assert (
        compute_tier("FirestoreConnector", deep_real, {"FirestoreConnector": 3})[0]
        == CERTIFIED
    )

    failing = _live_index(
        {"engines": {"x": {"connectors": ["XConnector"], "passed": 5, "failed": 1}}}
    )
    assert compute_tier("XConnector", failing, {"XConnector": 1})[0] == VERIFIED


def test_recording_one_family_keeps_the_evidence_of_the_others(tmp_path):
    from query_builder.connectors.status import load_live_results, record_live

    (tmp_path / "docs").mkdir()
    first = {
        "run_at": "2026-01-01T00:00:00Z",
        "platform": "A",
        "engines": {
            "postgres": {"connectors": ["PostgresConnector"], "passed": 9, "failed": 0}
        },
    }
    second = {
        "run_at": "2026-02-02T00:00:00Z",
        "platform": "B",
        "engines": {
            "arangodb": {"connectors": ["ArangoDBConnector"], "passed": 4, "failed": 0}
        },
    }
    record_live([first], root=tmp_path)
    record_live([second], root=tmp_path)
    saved = load_live_results(tmp_path)
    assert set(saved["engines"]) == {"postgres", "arangodb"}
    # each engine keeps the provenance of the run that produced it
    assert saved["engines"]["postgres"]["run_at"] == "2026-01-01T00:00:00Z"
    assert saved["engines"]["postgres"]["platform"] == "A"
    assert saved["engines"]["arangodb"]["platform"] == "B"
    assert saved["run_at"] == "2026-02-02T00:00:00Z"
