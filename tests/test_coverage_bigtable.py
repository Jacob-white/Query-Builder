"""Mock tests for the Bigtable row reader (key ranges, client-side filters, ordering)."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from query_builder.connectors import bigtable as bt
from query_builder.connectors._sql_subset import Predicate, SubsetPlan


def test_cell_text_decodes_utf8_or_hex() -> None:
    assert bt.cell_text(b"abc") == "abc"
    assert bt.cell_text(bytearray(b"abc")) == "abc"
    assert bt.cell_text(b"\xff\x00") == "0xff00"
    assert bt.cell_text(7) == 7 and bt.cell_text(None) is None


def _row(key: bytes, cells: dict[str, dict[bytes, list[bytes]]] | None) -> Any:
    wrapped = {
        fam: {q: [SimpleNamespace(value=v) for v in vals] for q, vals in quals.items()}
        for fam, quals in (cells or {}).items()
    }
    return SimpleNamespace(row_key=key, cells=wrapped if cells is not None else None)


def test_row_record_flattens_latest_cells() -> None:
    row = _row(
        b"k1", {"cf": {b"a": [b"new", b"old"], b"empty": []}, "g": {b"\xff": [b"1"]}}
    )
    assert bt._row_record(row) == {"row_key": "k1", "cf.a": "new", "g.0xff": "1"}
    assert bt._row_record(_row(b"k2", None)) == {"row_key": "k2"}


def test_number_and_compare_semantics() -> None:
    assert (
        bt._number(True) is None and bt._number(3) == 3.0 and bt._number("2.5") == 2.5
    )
    assert (
        bt._number("abc") is None
        and bt._number(None) is None
        and bt._number([1]) is None
    )
    assert bt._compare("10", ">", "9")  # numeric, not lexicographic
    assert not bt._compare("10", "<", 9)
    assert bt._compare("abc", "<", "abd") and bt._compare("a", "!=", "b")
    assert (
        bt._compare(5, ">=", 5.0)
        and bt._compare(5, "<=", "5")
        and bt._compare("x", "=", "x")
    )


@pytest.mark.parametrize(
    ("pred", "record", "expected"),
    [
        (Predicate("a", "is-null"), {}, True),
        (Predicate("a", "is-null"), {"a": 1}, False),
        (Predicate("a", "is-not-null"), {"a": 1}, True),
        (Predicate("a", "is-not-null"), {}, False),
        (Predicate("a", "="), {}, False),  # NULL never satisfies a comparison
        (Predicate("a", "prefix", "ab"), {"a": "abc"}, True),
        (Predicate("a", "prefix", "ab"), {"a": "xab"}, False),
        (Predicate("a", "in", [1, "2"]), {"a": "2"}, True),
        (Predicate("a", "in", [1, 2]), {"a": 3}, False),
        (Predicate("a", "not-in", [1, 2]), {"a": 3}, True),
        (Predicate("a", "not-in", [1, 2]), {"a": "2"}, False),
        (Predicate("a", "not-in", [1]), {}, False),
        (Predicate("a", ">", 1), {"a": "5"}, True),
    ],
)
def test_matches(pred: Predicate, record: dict[str, Any], expected: bool) -> None:
    assert bt._matches(record, pred) is expected


def test_sort_key_orders_numbers_text_then_null() -> None:
    values = [None, "b", 10, "a", 2, "3"]
    assert sorted(values, key=bt._sort_key) == [2, "3", 10, "a", "b", None]


def _plan(*preds: Predicate, **kw: Any) -> SubsetPlan:
    return SubsetPlan(table="t", columns=None, predicates=list(preds), **kw)


def test_key_range_translation() -> None:
    rk = bt.ROW_KEY
    assert bt._key_range(_plan(Predicate(rk, "=", "k"))) == {
        "start_key": b"k",
        "end_key": b"k",
        "end_inclusive": True,
    }
    assert bt._key_range(_plan(Predicate(rk, ">=", "a"), Predicate(rk, ">", "zz"))) == {
        "start_key": b"a"  # first lower bound wins; the rest are filtered client-side
    }
    assert bt._key_range(_plan(Predicate(rk, ">", "a"))) == {"start_key": b"a\x00"}
    assert bt._key_range(_plan(Predicate(rk, "<", "m"), Predicate(rk, "<=", "z"))) == {
        "end_key": b"m",
        "end_inclusive": False,
    }
    assert bt._key_range(_plan(Predicate(rk, "<=", "m"))) == {
        "end_key": b"m",
        "end_inclusive": True,
    }
    assert bt._key_range(_plan(Predicate(rk, "prefix", "ab"))) == {
        "start_key": b"ab",
        "end_key": b"ac",
        "end_inclusive": False,
    }
    assert bt._key_range(_plan(Predicate(rk, "prefix", ""))) == {"start_key": b""}
    open_ended = bt._key_range(_plan(Predicate(rk, "prefix", "\xff")))
    assert open_ended["start_key"] == "\xff".encode()
    # unsupported-for-pushdown predicates and other columns are ignored
    assert (
        bt._key_range(
            _plan(
                Predicate(rk, "in", ["a"]),
                Predicate(rk, "!=", "a"),
                Predicate(rk, "is-null"),
                Predicate("cf.q", "=", "x"),
            )
        )
        == {}
    )


class _Table:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.kwargs: dict[str, Any] = {}

    def read_rows(self, **kw: Any) -> list[Any]:
        self.kwargs = kw
        return self.rows


def _instance(rows: list[Any]) -> tuple[Any, _Table]:
    table = _Table(rows)
    return SimpleNamespace(table=lambda name: table), table


ROWS = [
    _row(b"k1", {"cf": {b"n": [b"10"], b"s": [b"b"]}}),
    _row(b"k2", {"cf": {b"n": [b"9"], b"s": [b"a"]}}),
    _row(b"k3", {"cf": {b"n": [b"100"]}}),
]


def test_read_records_filters_sorts_and_pages() -> None:
    inst, table = _instance(ROWS)
    plan = _plan(
        Predicate("cf.n", ">", 5),
        order_by=[("cf.n", True)],
        limit=2,
        offset=1,
    )
    got = bt.read_records(inst, plan)
    assert [r["row_key"] for r in got] == ["k1", "k2"]  # n desc: k3(100), k1(10), k2(9)
    assert "limit" not in table.kwargs  # predicates/ordering prevent limit pushdown
    # ORDER BY text with a NULL: NULL sorts last ascending
    plan2 = _plan(order_by=[("cf.s", False)])
    assert [r["row_key"] for r in bt.read_records(inst, plan2)] == ["k2", "k1", "k3"]


def test_read_records_pushes_limit_down_for_plain_scans() -> None:
    inst, table = _instance(ROWS)
    assert len(bt.read_records(inst, _plan(limit=2, offset=1))) == 2
    assert table.kwargs["limit"] == 3
    inst2, table2 = _instance(ROWS)
    bt.read_records(inst2, _plan(Predicate(bt.ROW_KEY, "=", "k1")))
    assert "limit" not in table2.kwargs and table2.kwargs["start_key"] == b"k1"


def test_read_records_applies_latest_version_filter_when_sdk_available() -> None:
    seen: list[int] = []
    rf = ModuleType("google.cloud.bigtable.row_filters")
    rf.CellsColumnLimitFilter = lambda n: seen.append(n) or f"limit-{n}"  # type: ignore[attr-defined]
    pkg = ModuleType("google.cloud.bigtable")
    pkg.row_filters = rf  # type: ignore[attr-defined]
    cloud = ModuleType("google.cloud")
    cloud.bigtable = pkg  # type: ignore[attr-defined]
    google = ModuleType("google")
    google.cloud = cloud  # type: ignore[attr-defined]
    inst, table = _instance([])
    with patch.dict(
        sys.modules,
        {
            "google": google,
            "google.cloud": cloud,
            "google.cloud.bigtable": pkg,
            "google.cloud.bigtable.row_filters": rf,
        },
    ):
        bt.read_records(inst, _plan())
    assert table.kwargs["filter_"] == "limit-1" and seen == [1]


def test_shape_records() -> None:
    recs = [{"row_key": "a", "cf.x": 1}, {"row_key": "b", "cf.y": 2}]
    assert bt.shape_records(_plan(count_star=True, count_alias="n"), recs) == (
        [("n",)],
        [[2]],
    )
    assert bt.shape_records(_plan(), recs) == (
        [("row_key",), ("cf.x",), ("cf.y",)],
        [["a", 1, None], ["b", None, 2]],
    )
    assert bt.shape_records(_plan(), []) == ([("row_key",)], [])
    named = SubsetPlan(table="t", columns=["cf.x"], out_names=["x"])
    assert bt.shape_records(named, recs) == ([("x",)], [[1], [None]])
