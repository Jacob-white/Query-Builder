"""Golden-snapshot tests for ``_extract_from_body``.

Expected values (the table below and ``regex_golden_adapters.json`` ``from_body``) were
captured from the original slice-per-character implementation before the rewrite; the
original code is intentionally not kept in the repository.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from query_builder.ast_validator import _extract_from_body

CORPUS = json.loads(
    (Path(__file__).parent / "fixtures" / "regex_golden_adapters.json").read_text(
        encoding="utf-8"
    )
)["from_body"]

TABLE = [
    ("users, auth_user) s", 0, "users, auth_user"),
    ("a JOIN b ON x WHERE y", 0, "a JOIN b ON x"),
    ("t group  by x", 0, "t"),
    ("t1, (select 1 where 1) q order by z", 0, "t1, (select 1 where 1) q"),
    ('"w""here" , b limit 3', 0, '"w""here" , b'),
    ("x; y", 0, "x"),
    ("format x", 0, "format x"),
    ("t [where] u forx", 0, "t [where] u forx"),
]


def test_table() -> None:
    for sql, start, expected in TABLE:
        assert _extract_from_body(sql, start) == expected


def test_golden_corpus() -> None:
    assert len(CORPUS) >= 300
    for (sql, start), expected in CORPUS:
        assert _extract_from_body(sql, start) == expected, sql


def test_long_input_is_linear() -> None:
    sql = "table_a, " * 25_000 + "table_b"
    start = time.perf_counter()
    assert _extract_from_body(sql, 0) == sql
    assert time.perf_counter() - start < 2.0
    sql = "a " + "(" * 50_000
    start = time.perf_counter()
    _extract_from_body(sql, 0)
    assert time.perf_counter() - start < 2.0
