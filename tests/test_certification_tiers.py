"""Every tier boundary of the depth-based certification rule (``status.compute_tier``)."""

from __future__ import annotations

import pytest

from query_builder.connectors import status

KEY = "m.PostgresLike"


def _cat(passed=1, failed=0, xfailed=0, verified=0, unverified=0, env=0):
    return {
        "passed": passed,
        "failed": failed,
        "xfailed": xfailed,
        "skipped": {
            "verified_limitation": verified,
            "declared_unverified": unverified,
            "environment": env,
        },
    }


def _rec(kind="sql", cats=None, **over):
    core = [c for c in status.CORE_BY_KIND[kind] if c != "async_parity"]
    categories = {c: _cat() for c in core}
    categories.update(cats or {})
    rec = {
        "connectors": [KEY],
        "version": "1.0",
        "passed": 50,
        "failed": 0,
        "xfailed": 0,
        "skipped": 3,
        "family_kind": kind,
        "core": core,
        "categories": categories,
        "limitations": {"verified": [], "declared_unverified": []},
    }
    rec.update(over)
    return rec


def _tier(*records, unit=2):
    live = {"engines": {f"e{i}": r for i, r in enumerate(records)}}
    index = status._live_index(live)
    return status.compute_tier(KEY, index, {KEY: unit})


def test_every_core_category_covered_is_certified():
    tier, why = _tier(_rec())
    assert tier == status.CERTIFIED
    assert "17/17 core categories" in why


@pytest.mark.parametrize("kind", ["sql", "native"])
def test_certified_for_both_families(kind):
    assert _tier(_rec(kind))[0] == status.CERTIFIED


def test_missing_core_category_is_basic():
    rec = _rec()
    del rec["categories"]["joins"]
    tier, why = _tier(rec)
    assert tier == status.BASIC
    assert "16/17" in why and "missing joins" in why


def test_core_category_with_zero_passes_and_no_skip_is_missing():
    tier, why = _tier(_rec(cats={"pagination": _cat(passed=0)}))
    assert tier == status.BASIC and "missing pagination" in why


def test_a_probe_verified_limitation_covers_a_core_category():
    rec = _rec(cats={"statement_timeout": _cat(passed=0, verified=1)})
    assert _tier(rec)[0] == status.CERTIFIED


def test_unverified_skip_in_a_core_category_blocks_certified():
    rec = _rec(cats={"joins": _cat(passed=3, unverified=1)})
    tier, why = _tier(rec)
    assert tier == status.BASIC and "unverified skips in joins" in why


def test_unverified_skip_that_is_the_only_evidence_is_also_missing():
    rec = _rec(cats={"statement_timeout": _cat(passed=0, unverified=1)})
    tier, why = _tier(rec)
    assert tier == status.BASIC and "missing statement_timeout" in why


def test_unverified_skip_outside_core_does_not_block():
    rec = _rec(
        cats={"window": _cat(passed=0, unverified=1), "secrets": _cat(0, unverified=1)}
    )
    assert _tier(rec)[0] == status.CERTIFIED


def test_environment_skip_alone_is_not_coverage():
    rec = _rec(cats={"joins": _cat(passed=0, env=4)})
    assert _tier(rec)[0] == status.BASIC


def test_any_failure_blocks_both_live_tiers():
    tier, why = _tier(_rec(failed=1))
    assert tier == status.VERIFIED and "1 failed" in why
    failing_cat = _rec(cats={"filters": _cat(passed=5, failed=1)}, failed=1)
    assert _tier(failing_cat)[0] == status.VERIFIED


def test_known_issues_block_certified():
    tier, why = _tier(_rec(xfailed=2))
    assert tier == status.VERIFIED and "2 known issues" in why


def test_failed_category_is_not_covered_even_if_totals_were_ignored():
    d = status.depth(_rec(cats={"filters": _cat(passed=5, failed=1)}))
    assert d is not None and "filters" in d["missing"] and not d["meets_bar"]


def test_old_format_report_can_never_be_certified():
    old = _rec()
    for k in ("categories", "core", "family_kind", "limitations"):
        del old[k]
    tier, why = _tier(old)
    assert tier == status.BASIC and "no per-category evidence" in why
    assert status.depth(old) is None


def test_empty_categories_dict_counts_as_old_format():
    assert _tier(_rec(categories={}))[0] == status.BASIC


def test_nothing_passed_is_not_live_evidence():
    assert _tier(_rec(passed=0))[0] == status.VERIFIED
    assert _tier(_rec(passed=0), unit=0)[0] == status.EXPERIMENTAL


def test_emulated_keeps_its_tier_and_exposes_the_depth():
    tier, why = _tier(_rec(emulated=True))
    assert tier == status.EMULATED and "depth bar met" in why
    shallow = _rec(emulated=True)
    del shallow["categories"]["ordering"]
    tier, why = _tier(shallow)
    assert tier == status.EMULATED
    assert "depth bar not met" in why and "missing ordering" in why
    old = _rec(emulated=True)
    del old["categories"]
    assert "no per-category evidence" in _tier(old)[1]


def test_async_parity_is_required_only_when_listed_in_core():
    sync_only = _rec()
    assert "async_parity" not in sync_only["core"]
    assert _tier(sync_only)[0] == status.CERTIFIED
    with_async = _rec(core=[*status.SQL_CORE])  # engine has an async class
    tier, why = _tier(with_async)
    assert tier == status.BASIC and "missing async_parity" in why
    with_async["categories"]["async_parity"] = _cat()
    assert _tier(with_async)[0] == status.CERTIFIED


def test_native_core_is_its_own_list():
    rec = _rec("native")
    assert "read_filtered" in rec["core"] and "joins" not in rec["core"]
    del rec["categories"]["value_safety"]
    tier, why = _tier(rec)
    assert tier == status.BASIC and "value_safety" in why
    # a smoke-level native run (connect/introspect/one read/writes refused) is only basic
    smoke = _rec(
        "native",
        categories={
            "connect": _cat(),
            "introspect": _cat(),
            "read_basic": _cat(),
            "write_refused": _cat(),
        },
    )
    tier, why = _tier(smoke)
    assert tier == status.BASIC and "4/9" in why


def test_best_evidence_wins_across_engines_of_one_class():
    deep = _rec(passed=40)
    shallow = _rec(passed=400)
    del shallow["categories"]["joins"]
    old = _rec(passed=900)
    del old["categories"]
    failing = _rec(passed=1000, failed=2)
    # order must not matter
    for order in ([deep, shallow, old, failing], [failing, old, shallow, deep]):
        assert _tier(*order)[0] == status.CERTIFIED
    assert _tier(shallow, old, failing)[0] == status.BASIC
    # a real-but-shallow run beats an emulator that met the bar
    emu = _rec(emulated=True)
    assert _tier(shallow, emu)[0] == status.BASIC
    assert _tier(emu)[0] == status.EMULATED
    # more covered core categories beats more passes
    best = status._live_index({"engines": {"a": shallow, "b": old}})[KEY]
    assert best["engine"] == "a"


def test_depth_lists_unverified_and_verified_limitations():
    rec = _rec(
        limitations={"verified": ["window"], "declared_unverified": ["right_join"]}
    )
    d = status.depth(rec)
    assert d["declared_unverified"] == ["right_join"]
    assert d["verified_limitations"] == ["window"]
    assert status.core_label(d) == "17/17 core categories"
    assert status.core_label(None) == "no category evidence"


def test_render_shows_depth_columns_and_legend():
    rec = _rec(
        cats={"joins": _cat(passed=3, unverified=1)},
        limitations={"verified": [], "declared_unverified": ["right_join"]},
    )
    report = {
        "totals": {
            "classes": 1,
            "sync": 1,
            "async": 0,
            "registered_names": 1,
            "tiers": {status.BASIC: 1},
        },
        "live_run_at": "2026-01-01",
        "live_engines": [
            {
                "engine": "e0",
                "version": "1",
                "passed": 50,
                "failed": 0,
                "xfailed": 0,
                "skipped": 3,
                "depth": status.depth(rec),
                "run_at": "2026-01-01",
                "platform": "p",
            }
        ],
        "connectors": [
            {
                "class": "PostgresLike",
                "mode": "sync",
                "tier": status.BASIC,
                "extra": None,
                "name": "pg",
                "aliases": [],
                "live": {
                    "engine": "e0",
                    "passed": 50,
                    "failed": 0,
                    "xfailed": 0,
                    "skipped": 3,
                    "depth": status.depth(rec),
                },
            }
        ],
    }
    md = status.render_markdown(report)
    assert "17/17 core categories" in md
    assert "1: `right_join`" in md
    assert "tiers measure testing depth" in md
    assert "`verified_limitation`" in md and "`declared_unverified`" in md
    table = status.render_table({**report, "connectors": [{**report["connectors"][0]}]})
    assert "CORE" in table and "17/17" in table
    summary = status.render_live_summary({"engines": {"e0": rec}})
    assert "17/17" in summary and "basic depth" in summary
