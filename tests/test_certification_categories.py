"""Default-suite tests for the live suite's category / limitation machinery (no services)."""

from __future__ import annotations

import collections

import pytest

from query_builder.connectors import status
from tests.integration import cases, conftest, limits, smoke
from tests.integration import categories as cat
from tests.integration import engines as eng
from tests.integration.engines import Limitation, as_limitation, run_probe


def test_every_query_case_has_a_known_category_and_every_sql_core_is_reachable():
    seen = collections.Counter(c.category for c in cases.CASES)
    assert set(seen) <= cat.ALL_CATEGORIES, set(seen) - cat.ALL_CATEGORIES
    assert "uncategorized" not in seen
    # the declarative battery feeds these SQL core categories; the others come from the
    # dedicated tests in test_conformance.py (introspection, write_refused, timeout, ...)
    from_cases = {
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
    }
    assert from_cases <= set(seen), from_cases - set(seen)


def test_case_category_mapping_examples():
    assert cat.case_category("order", "offset-past-end") == "pagination"
    assert (
        cat.case_category("filter", "filter-in-subquery", ("in_subquery",))
        == "subquery_cte"
    )
    assert cat.case_category("aggregate", "aggregate-null-handling") == "null_handling"
    assert cat.case_category("window", "w") == "window"
    assert cat.case_category("nonsense", "x") == "uncategorized"


def test_core_lists_are_shared_with_status_and_async_is_conditional():
    assert cat.SQL_CORE_CATEGORIES == status.SQL_CORE
    assert cat.NATIVE_CORE_CATEGORIES == status.NATIVE_CORE
    assert "async_parity" in cat.core_for("sql", True)
    assert "async_parity" not in cat.core_for("sql", False)
    assert "read_filtered" in cat.core_for("native", False)
    assert "joins" not in cat.core_for("native", True)


def test_all_test_modules_tag_their_tests():
    """Every live test function must carry a qb_category marker (or be fed by Case.category)."""
    import ast
    from pathlib import Path

    root = Path(__file__).parent / "integration"
    untagged: list[str] = []
    for path in sorted(root.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        module_tagged = any(
            isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "pytestmark" for t in n.targets)
            and "qb_category" in ast.unparse(n)
            for n in tree.body
        )
        for node in tree.body:
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name.startswith("test_"):
                tagged = module_tagged or any(
                    "qb_category" in ast.unparse(d) or ast.unparse(d).startswith("cat(")
                    for d in node.decorator_list
                )
                if not tagged and node.name != "test_compile_and_execute":
                    untagged.append(f"{path.name}::{node.name}")
    assert not untagged, untagged


def test_classify_skip():
    assert cat.classify_skip(cat.limitation_reason("e", "having", "no HAVING")) == (
        "limitation",
        "having",
    )
    assert cat.classify_skip(cat.environment_reason("anything"))[0] == "environment"
    assert cat.classify_skip("pg not reachable at 127.0.0.1:1")[0] == "environment"
    assert cat.classify_skip("driver not installed (need psycopg)")[0] == "environment"
    assert cat.classify_skip("x: set QB_IT_X_HOST to run this test")[0] == "environment"
    assert cat.classify_skip("something else entirely") == ("other", None)


def test_plain_string_limitation_is_unprobed_and_backward_compatible():
    lim = as_limitation("no foreign keys")
    assert lim == Limitation("no foreign keys") and lim.probe is None
    assert as_limitation(lim) is lim
    e = eng.ENGINES["clickhouse"]  # declared with a plain string in the merged registry
    got = e.limitation("introspect_fk")
    assert got is not None and got.probe is None and "foreign keys" in got.reason
    assert e.limitation("window") is None


def test_every_registered_limitation_normalises():
    declared = limits.all_declared()
    assert declared, "no declared limitations at all?"
    for (name, feature), lim in declared.items():
        assert isinstance(lim, Limitation) and lim.reason, (name, feature)
        assert lim.probe is None or callable(lim.probe) or isinstance(lim.probe, str)


def test_probe_semantics_rejected_vs_accepted():
    fake = eng.Engine(
        name="fake", connector="x", tier="embedded", family="", drivers=(), pip=""
    )
    assert run_probe(fake, Limitation("r", probe=lambda e: False))[0] is True
    assert run_probe(fake, Limitation("r", probe=lambda e: True))[0] is False

    def boom(e: eng.Engine) -> bool:
        raise RuntimeError("syntax error")

    rejected, detail = run_probe(fake, Limitation("r", probe=boom))
    assert rejected and "RuntimeError" in detail
    with pytest.raises(ValueError):
        run_probe(fake, Limitation("r"))


def test_statement_probe_runs_through_the_native_driver():
    class _Native:
        def __init__(self, fail: bool) -> None:
            self.fail, self.ran, self.closed = fail, [], False

        def run(self, stmt: str) -> None:
            self.ran.append(stmt)
            if self.fail:
                raise RuntimeError("unsupported")

        def close(self) -> None:
            self.closed = True

    for fail, expect_rejected in ((True, True), (False, False)):
        native = _Native(fail)
        e = eng.Engine(
            name="fake",
            connector="x",
            tier="embedded",
            family="",
            drivers=(),
            pip="",
            native_factory=lambda _e, n=native: n,
        )
        rejected, _ = run_probe(e, Limitation("r", probe="SET x = 1"))
        assert (
            rejected is expect_rejected
            and native.ran == ["SET x = 1"]
            and native.closed
        )


def test_sqlite_probes_confirm_its_declared_limitations_in_process():
    e = eng.ENGINES["sqlite"]
    for feature in ("statement_timeout", "case_sensitive_identifiers"):
        lim = e.limitation(feature)
        assert lim is not None and lim.probe is not None, feature
        rejected, detail = run_probe(e, lim)
        assert rejected, f"sqlite {feature}: {detail}"


def test_duckdb_probes_confirm_its_declared_limitations_in_process():
    pytest.importorskip("duckdb")
    e = eng.ENGINES["duckdb"]
    for feature in ("statement_timeout", "case_sensitive_identifiers"):
        lim = e.limitation(feature)
        assert lim is not None and lim.probe is not None, feature
        rejected, detail = run_probe(e, lim)
        assert rejected, f"duckdb {feature}: {detail}"


def test_a_wrong_declaration_is_caught_by_its_probe():
    """SQLite DOES support a feature we pretend it lacks: the probe must report ACCEPTED."""
    e = eng.ENGINES["sqlite"]
    wrong = Limitation("sqlite cannot select 1", probe="SELECT 1")
    rejected, detail = run_probe(e, wrong)
    assert rejected is False and "ACCEPTED" in detail


def _rec(skips, cats=None):
    return {"cats": cats or collections.defaultdict(cat.empty_category), "skips": skips}


def test_classify_skips_marks_probe_confirmed_limitations_verified(monkeypatch):
    monkeypatch.setitem(conftest._PROBES, ("sqlite", "statement_timeout"), True)
    monkeypatch.setitem(
        conftest._PROBES, ("sqlite", "case_sensitive_identifiers"), False
    )
    ev = conftest.classify_skips(
        "sqlite",
        _rec(
            [
                ("statement_timeout", "limitation", "statement_timeout"),
                ("identifier_quoting", "limitation", "case_sensitive_identifiers"),
                (
                    "joins",
                    "limitation",
                    "right_join",
                ),  # unprobed string declaration? none
                ("connect", "environment", None),
                ("pagination", "other", None),
            ]
        ),
    )
    c = ev["categories"]
    assert c["statement_timeout"]["skipped"]["verified_limitation"] == 1
    # the probe ran and the engine ACCEPTED it: the declaration is wrong, never verified
    assert c["identifier_quoting"]["skipped"]["declared_unverified"] == 1
    assert c["joins"]["skipped"]["declared_unverified"] == 1
    assert c["connect"]["skipped"]["environment"] == 1
    assert (
        c["pagination"]["skipped"]["declared_unverified"] == 1
    )  # untested = unverified
    assert ev["limitations"]["verified"] == ["statement_timeout"]
    assert "right_join" in ev["limitations"]["declared_unverified"]


def test_probe_that_never_ran_leaves_the_limitation_unverified(monkeypatch):
    monkeypatch.delitem(
        conftest._PROBES, ("sqlite", "statement_timeout"), raising=False
    )
    ev = conftest.classify_skips(
        "sqlite", _rec([("statement_timeout", "limitation", "statement_timeout")])
    )
    assert ev["categories"]["statement_timeout"]["skipped"]["declared_unverified"] == 1


def test_native_smoke_engines_declare_checks_or_limitations():
    for name in (
        "mongodb",
        "redis",
        "elasticsearch",
        "opensearch",
        "neo4j",
        "cassandra",
    ):
        sm = smoke.SMOKE[name]
        for category in ("read_filtered", "ordering", "pagination", "value_safety"):
            assert sm.checks.get(category) or category in sm.limitations, (
                name,
                category,
            )
        assert sm.bad_queries, name
        assert sm.extra_seed is not None, name
        assert len(sm.writes) >= 4, name


def test_redis_and_cassandra_limitations_carry_probes():
    assert smoke.SMOKE["redis"].limitations["spec_compile"].probe is not None
    assert smoke.SMOKE["cassandra"].limitations["ordering"].probe is not None
    ids = limits.probe_ids()
    assert "redis::spec_compile" in ids and "cassandra::ordering" in ids
    assert "sqlite::statement_timeout" in ids
