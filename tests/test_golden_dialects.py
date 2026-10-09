"""Golden snapshot of every registered dialect's observable behaviour.

The snapshot (``tests/golden/dialects.json``) was captured from the unrefactored
``query_builder/dialects.py`` and guards structural refactors of the dialect
code: registry names/aliases, class names, class-level attributes and the output
(or exception) of every public formatting method over an input matrix.

Regenerate deliberately with ``python tests/test_golden_dialects.py --update``.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

from query_builder import dialects as d

GOLDEN = Path(__file__).parent / "golden" / "dialects.json"

_ATTRS = (
    "name",
    "placeholder",
    "pagination_placement",
    "requires_order_by_for_pagination",
    "supports_cte",
    "supports_recursive_cte",
    "supports_materialized_cte",
    "supports_window_functions",
    "supports_window_groups_frame",
    "avg_template",
    "count_distinct_template",
    "subquery_alias_keyword",
    "neq_operator",
    "like_escape_char",
    "like_escape_clause",
    "like_special_chars",
)

_IDENTS = ["users", "public.users", "a.b.c", "x" * 129, "bad name", "1abc", "", "t;--"]
_ALIASES = ["total", 'we"ird', "a b", "x" * 300, "ctl\x01", "tab\t", "été"]
_COLS = ['"t"."c"', "t.c", "col"]
_LIKE_VALUES = ["abc", "50%", "a_b", "back\\slash", "~tilde", 5]
_METRICS = ["cosine", "l2", "euclidean", "dot_product", "inner_product", "other", "L2"]
_LIMITS = [(10, 0), (5, 20), (0, 0)]
_VECTORS = [[0.1, 0.2], [], [1]]
_SCHEMAS = [("public", None), ("sch", "tbl")]
_TEXT = [([], None), (["a"], None), (["a", "b"], "?"), (["t.c"], "$1")]


def _call(fn: Any, *args: Any) -> Any:
    try:
        out = fn(*args)
    except Exception as exc:
        return {"exc": type(exc).__name__, "msg": str(exc)}
    return json.loads(json.dumps(out, default=repr))


def snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {
        "names": sorted(d.DIALECTS),
        # Every importable name (classes, helpers, constants, private helpers),
        # excluding submodules and the incidental ``Any`` import.
        "module_names": sorted(
            n
            for n, v in vars(d).items()
            if not n.startswith("__") and not inspect.ismodule(v) and v is not Any
        ),
        "distinct_instances": len({id(v) for v in d.DIALECTS.values()}),
        "dialects": {},
    }
    for reg_name in sorted(d.DIALECTS):
        dia = d.DIALECTS[reg_name]
        rec: dict[str, Any] = {
            "cls": type(dia).__name__,
            "mro": [c.__name__ for c in type(dia).__mro__],
            "attrs": {a: getattr(dia, a) for a in _ATTRS},
        }
        m: dict[str, Any] = {}
        m["quote_identifier"] = [[i, _call(dia.quote_identifier, i)] for i in _IDENTS]
        m["quote_alias"] = [[a, _call(dia.quote_alias, a)] for a in _ALIASES]
        m["format_ilike"] = [_call(dia.format_ilike, c) for c in _COLS]
        m["format_like"] = [_call(dia.format_like, c) for c in _COLS]
        m["format_substring_match"] = [
            _call(dia.format_substring_match, c) for c in _COLS
        ]
        m["escape_like"] = [_call(dia.escape_like, v) for v in _LIKE_VALUES]
        m["substring_param"] = [
            [mode, _call(dia.substring_param, mode, v)]
            for mode in ("contains", "starts", "ends")
            for v in _LIKE_VALUES
        ]
        m["format_cte_materialized"] = [
            _call(dia.format_cte_materialized, x) for x in (None, True, False)
        ]
        m["format_limit_offset"] = [
            _call(dia.format_limit_offset, *lo) for lo in _LIMITS
        ]
        m["format_vector_distance"] = [
            [c, mt, _call(dia.format_vector_distance, c, mt)]
            for c in _COLS[:2]
            for mt in _METRICS
        ]
        m["format_vector_distance_default"] = _call(dia.format_vector_distance, "c")
        m["format_vector_param"] = [_call(dia.format_vector_param, v) for v in _VECTORS]
        m["format_text_search"] = [
            _call(dia.format_text_search, cols, ph) for cols, ph in _TEXT
        ]
        for meth in (
            "inspect_tables_query",
            "inspect_tables",
        ):
            m[meth] = [_call(getattr(dia, meth), s) for s in ("public", "sch")]
            m[meth + "_default"] = _call(getattr(dia, meth))
        for meth in (
            "inspect_columns_query",
            "inspect_columns",
            "inspect_primary_keys_query",
            "inspect_primary_keys",
            "inspect_foreign_keys_query",
            "inspect_foreign_keys",
        ):
            m[meth] = [_call(getattr(dia, meth), s, t) for s, t in _SCHEMAS]
            m[meth + "_default"] = _call(getattr(dia, meth))
        rec["methods"] = m
        snap["dialects"][reg_name] = rec
    snap["helpers"] = {
        "get_dialect": [
            [n, type(d.get_dialect(n)).__name__]
            for n in (None, "PostgreSQL ", "nope", "SQLSERVER", "spark")
        ],
        "quote_identifier": _call(d.quote_identifier, "a.b", "mysql"),
        "quote_alias": _call(d.quote_alias, "a", "mssql"),
        "list_dialects": d.list_dialects(),
    }
    return snap


def test_dialects_match_golden_snapshot() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(snapshot()))
    assert actual["names"] == expected["names"]
    assert actual["module_names"] == expected["module_names"]
    assert actual["distinct_instances"] == expected["distinct_instances"]
    assert actual["helpers"] == expected["helpers"]
    for name, rec in expected["dialects"].items():
        assert actual["dialects"][name] == rec, name


if __name__ == "__main__":
    if "--update" in sys.argv:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(
            json.dumps(snapshot(), indent=1, sort_keys=True), encoding="utf-8"
        )
        print("wrote", GOLDEN)
