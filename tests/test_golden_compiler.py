"""Golden (snapshot) tests pinning the exact SQL/params ``QueryCompiler`` emits.

These guard behaviour-preserving refactors of ``query_builder.compiler``: a
broad matrix of spec shapes is compiled against every registered dialect and
compared with ``tests/golden/compiler_golden.json``. A handful of mainstream
dialects are stored verbatim (readable diffs); every other dialect is stored
as a SHA-256 of its canonical JSON so the snapshot stays small.

Regenerate deliberately (never to make a refactor pass) with::

    QB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden_compiler.py
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from query_builder.compiler import QueryCompiler, validate_query_spec
from query_builder.dialects import get_dialect, list_dialects
from query_builder.middleware import MiddlewarePipeline

GOLDEN_DIR = Path(__file__).parent / "golden"
COMPILE_GOLDEN = GOLDEN_DIR / "compiler_golden.json"
VALIDATE_GOLDEN = GOLDEN_DIR / "validate_golden.json"

VERBATIM_DIALECTS = (
    "postgres",
    "mysql",
    "mssql",
    "oracle",
    "sqlite",
    "bigquery",
    "clickhouse",
    "snowflake",
)

SCHEMA: dict[str, Any] = {
    "tables": {
        "users": {
            "columns": [
                {"name": "id", "is_primary": True},
                {"name": "email"},
                {"name": "name"},
                {"name": "age"},
                {"name": "status"},
                {"name": "client_id"},
                {"name": "created_at"},
                {"name": "embedding"},
                {"name": "bio"},
            ],
            "has_user_id": True,
            "user_col": "id",
        },
        "orders": {
            "columns": [
                {"name": "id", "is_primary": True},
                {"name": "user_id"},
                {"name": "total"},
                {"name": "status"},
                {"name": "created_at"},
                {"name": "client_id"},
            ],
        },
        "items": {
            "columns": [
                {"name": "id", "is_primary": True},
                {"name": "order_id"},
                {"name": "sku"},
                {"name": "qty"},
                {"name": "price"},
            ],
        },
        "notenant": {"columns": [{"name": "id"}, {"name": "label"}]},
    },
    "relationships": [
        {
            "source_table": "orders",
            "source_column": "user_id",
            "target_table": "users",
            "target_column": "id",
        },
    ],
    "foreign_keys": [
        {
            "table": "items",
            "column": "order_id",
            "foreign_table": "orders",
            "foreign_column": "id",
        }
    ],
}

OWNERSHIP = {
    "orders": [[("orders", "user_id", "users")]],
}


def _f(column: str, op: str = "eq", value: Any = None, **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"column": column, "op": op, "value": value}
    d.update(kw)
    return d


def _sub(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"table": "orders", "columns": ["user_id"]}
    base.update(kw)
    return base


# (name, spec, constructor kwargs). kwargs may contain the sentinel "NOSCHEMA".
CASES: list[tuple[str, dict[str, Any], dict[str, Any]]] = []


def case(name: str, spec: dict[str, Any], **kw: Any) -> None:
    CASES.append((name, spec, kw))


case("basic", {"table": "users", "columns": ["users.id", "users.email"], "limit": 10})
case("star_default_columns", {"table": "users"})
case("star_noschema", {"table": "users", "limit": 5}, schema=None)
case("star_explicit", {"table": "users", "columns": ["*"]})
case("table_star", {"table": "users", "columns": ["users.*"]})
case(
    "dict_cols",
    {
        "table": "users",
        "columns": [
            {"column": "id"},
            {"name": "email", "alias": "mail"},
            {"column": "name", "table": "users"},
            {"expression": "x"},
            {"column": 5},
        ],
    },
    validate_spec=False,
)
case("distinct", {"table": "users", "columns": ["status"], "distinct": True})
case("limit_offset", {"table": "users", "columns": ["id"], "limit": 25, "offset": 50})
case("limit_zero", {"table": "users", "columns": ["id"], "limit": 0})
case(
    "limit_clamped",
    {"table": "users", "columns": ["id"], "limit": 500, "offset": 9_999_999},
    validate_spec=False,
)
case("max_limit", {"table": "users", "columns": ["id"], "limit": 80}, max_limit=20)
case(
    "neg_offset",
    {"table": "users", "columns": ["id"], "offset": -5},
    validate_spec=False,
)
case(
    "order_by",
    {
        "table": "users",
        "columns": ["id", "name"],
        "order_by": [
            {"column": "name", "direction": "desc"},
            {"column": "id"},
            {"column": "age", "direction": "sideways", "table": "users"},
            {"direction": "asc"},
            {"column": "email", "tablePrefix": "users"},
        ],
    },
)
case(
    "order_by_only",
    {
        "table": "users",
        "columns": ["id"],
        "order_by": [{"column": "id", "direction": "DESC"}],
    },
)
case(
    "pagination_no_order",
    {"table": "users", "columns": ["id"], "limit": 3, "offset": 6},
)

# Aggregates / grouping
case(
    "agg_all",
    {
        "table": "orders",
        "columns": [
            "status",
            {"column": "total", "agg": "sum", "alias": "sum_total"},
            {"column": "total", "aggregate": "avg"},
            {"column": "total", "agg": "min"},
            {"column": "total", "agg": "max"},
            {"column": "id", "agg": "count"},
            {"column": "user_id", "agg": "count_distinct"},
            {"column": "*", "agg": "count"},
            {"column": "*", "agg": "count", "alias": "n"},
        ],
    },
)
case(
    "agg_star_distinct",
    {"table": "orders", "columns": [{"column": "*", "agg": "count_distinct"}]},
    validate_spec=False,
)
case(
    "agg_star_sum",
    {"table": "orders", "columns": [{"column": "*", "agg": "sum"}]},
    validate_spec=False,
)
case("agg_star_plain", {"table": "orders", "columns": [{"column": "*"}]})
case(
    "agg_having",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum", "alias": "s"}],
        "having": [
            {"column": "total", "agg": "sum", "op": "gt", "value": 100},
            {"column": "*", "agg": "count", "op": "gte", "value": 2},
            {"column": "total", "aggregate": "avg", "operator": "neq", "value": 0},
            {"column": "total", "agg": "bogus", "op": "gt", "value": 1},
            {"column": "total", "agg": "sum", "op": "bogus", "value": 1},
        ],
    },
    validate_spec=False,
)
case(
    "having_star_bad_agg",
    {
        "table": "orders",
        "columns": ["status"],
        "having": [{"column": "*", "agg": "sum", "op": "gt", "value": 1}],
    },
    validate_spec=False,
)
case(
    "having_simple",
    {
        "table": "orders",
        "columns": ["status", {"column": "id", "agg": "count"}],
        "having": [{"column": "id", "agg": "count", "op": "lt", "value": 9}],
    },
)
case(
    "distinct_with_agg",
    {
        "table": "orders",
        "columns": [{"column": "id", "agg": "count"}],
        "distinct": True,
    },
)
case(
    "grouping_rollup",
    {
        "table": "orders",
        "columns": ["status", "user_id", {"column": "total", "agg": "sum"}],
        "grouping_type": "rollup",
    },
)
case(
    "grouping_cube",
    {
        "table": "orders",
        "columns": ["status", "user_id", {"column": "total", "agg": "sum"}],
        "grouping_type": "cube",
    },
)
case(
    "rollup_cols",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum"}],
        "rollup": {"columns": ["status", "user_id"]},
    },
)
case(
    "rollup_nocols",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum"}],
        "rollup": {},
    },
)
case(
    "cube_cols",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum"}],
        "cube": {"columns": ["status", "user_id"]},
    },
)
case(
    "cube_nocols",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum"}],
        "cube": {},
    },
)
case(
    "grouping_sets",
    {
        "table": "orders",
        "columns": ["status", "user_id", {"column": "total", "agg": "sum"}],
        "grouping_sets": [["status"], ["user_id", "status"], []],
    },
)
case(
    "grouping_sets_empty",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum"}],
        "grouping_type": "grouping_sets",
        "grouping_sets": [],
    },
)
case(
    "grouping_type_standard",
    {
        "table": "orders",
        "columns": ["status", {"column": "total", "agg": "sum"}],
        "grouping_type": "standard",
    },
)
case(
    "grouping_no_agg",
    {"table": "orders", "columns": ["status"], "grouping_type": "rollup"},
)
case(
    "time_grain",
    {
        "table": "orders",
        "columns": [
            {"column": "created_at", "time_grain": "month"},
            {"column": "created_at", "grain": "day", "alias": "d"},
            {"column": "id", "agg": "count"},
        ],
    },
)
case(
    "case_when",
    {
        "table": "users",
        "columns": [
            {
                "case_when": {
                    "branches": [
                        {
                            "condition": {"column": "age", "op": "lt", "value": 18},
                            "then_value": "minor",
                        },
                        {
                            "condition": {
                                "column": "age",
                                "op": "between",
                                "value": [18, 65],
                            },
                            "then_value": "adult",
                        },
                        {
                            "condition": {
                                "column": "status",
                                "op": "in",
                                "value": ["a", "b"],
                            },
                            "then_column": "name",
                        },
                        {
                            "condition": {
                                "column": "status",
                                "op": "not_in",
                                "value": "z",
                            },
                            "then_value": 1,
                        },
                        {
                            "condition": {"column": "bio", "op": "is_null"},
                            "then_value": 2,
                        },
                        {
                            "condition": {"column": "bio", "operator": "is not null"},
                            "then_value": 3,
                        },
                        {
                            "condition": {"column": "bio", "op": "weird", "value": 9},
                            "then_value": 4,
                        },
                        {
                            "condition": {
                                "column": "age",
                                "op": "not between",
                                "value": 7,
                            },
                            "then_value": 5,
                        },
                    ],
                    "else_value": "senior",
                },
                "alias": "bucket",
            },
            {
                "case_when": {
                    "branches": [
                        {
                            "condition": {"column": "age", "op": "gt", "value": 1},
                            "then_value": "x",
                        }
                    ],
                    "else_column": "email",
                }
            },
            {
                "case_when": {
                    "branches": [
                        {
                            "condition": {"column": "age", "op": "gt", "value": 1},
                            "then_value": "x",
                        }
                    ]
                }
            },
        ],
    },
)
case(
    "window_functions",
    {
        "table": "orders",
        "columns": ["id"],
        "window_functions": [
            {
                "function": "row_number",
                "partition_by": ["user_id"],
                "order_by": [{"column": "created_at", "direction": "desc"}],
                "alias": "rn",
            },
            {
                "function": "sum",
                "arguments": ["total"],
                "partition_by": ["user_id"],
                "frame": {
                    "frame_type": "ROWS",
                    "start": "UNBOUNDED PRECEDING",
                    "end": "CURRENT ROW",
                },
                "alias": "running",
            },
            {"function": "count", "arguments": ["*"]},
            {"function": "count"},
            {"function": "rank", "order_by": [{"column": "total"}]},
            {
                "function": "sum",
                "arguments": ["total"],
                "frame": {"frame_type": "ROWS", "start": "2 PRECEDING"},
            },
            {"function": "sum", "arguments": ["total", 5]},
        ],
    },
)
case(
    "window_groups_frame",
    {
        "table": "orders",
        "columns": ["id"],
        "window_functions": [
            {
                "function": "sum",
                "arguments": ["total"],
                "order_by": [{"column": "id"}],
                "frame": {
                    "frame_type": "GROUPS",
                    "start": "1 PRECEDING",
                    "end": "CURRENT ROW",
                    "exclusion": "ties",
                },
            },
        ],
    },
)

# Joins
case(
    "join_auto_rel",
    {
        "table": "orders",
        "columns": ["orders.id", "users.email"],
        "joins": [{"table": "users"}],
    },
)
case(
    "join_auto_fk",
    {
        "table": "items",
        "columns": ["items.sku", "orders.total"],
        "joins": [{"table": "orders", "type": "inner"}],
    },
)
case(
    "join_on",
    {
        "table": "orders",
        "columns": ["orders.id", "u.email"],
        "joins": [
            {
                "table": "users",
                "alias": "u",
                "type": "right join",
                "on": [{"left": "orders.user_id", "right": "u.id"}],
            }
        ],
    },
)
case(
    "join_cols",
    {
        "table": "orders",
        "columns": ["orders.id", "users.email"],
        "joins": [
            {"table": "users", "type": "full", "left_col": "user_id", "right_col": "id"}
        ],
    },
)
case(
    "join_cols_lefttable",
    {
        "table": "items",
        "columns": ["items.id"],
        "joins": [
            {"table": "orders", "type": "inner"},
            {
                "table": "users",
                "left_table": "orders",
                "left_col": "user_id",
                "right_col": "id",
            },
        ],
    },
)
case(
    "join_bad_lefttable",
    {
        "table": "items",
        "columns": ["items.id"],
        "joins": [
            {
                "table": "users",
                "left_table": "ghost",
                "left_col": "user_id",
                "right_col": "id",
            }
        ],
    },
)
case(
    "join_weird_type",
    {
        "table": "orders",
        "columns": ["orders.id"],
        "joins": [{"table": "users", "type": "cross"}],
    },
    validate_spec=False,
)
case(
    "join_self_alias",
    {
        "table": "orders",
        "columns": ["orders.id"],
        "joins": [
            {"table": "orders", "on": [{"left": "orders.id", "right": "orders.id"}]}
        ],
    },
)
case(
    "join_missing_table",
    {"table": "orders", "columns": ["orders.id"], "joins": [{"type": "left"}]},
    validate_spec=False,
)
case(
    "join_unknown_table",
    {"table": "orders", "columns": ["orders.id"], "joins": [{"table": "ghost"}]},
    validate_spec=False,
)
case(
    "join_no_condition",
    {"table": "orders", "columns": ["orders.id"], "joins": [{"table": "notenant"}]},
)
case(
    "join_noschema_nocond",
    {"table": "orders", "columns": ["orders.id"], "joins": [{"table": "users"}]},
    schema=None,
)
case(
    "join_multi",
    {
        "table": "items",
        "columns": ["items.sku", "orders.total", "users.email"],
        "joins": [
            {"table": "orders", "type": "inner"},
            {"table": "users", "on": [{"left": "orders.user_id", "right": "users.id"}]},
        ],
    },
)
case(
    "join_filters_group",
    {
        "table": "orders",
        "columns": ["users.status", {"column": "total", "agg": "sum"}],
        "joins": [{"table": "users"}],
        "filters": [_f("status", "eq", "a", table="users")],
        "order_by": [{"column": "status", "table": "users"}],
    },
)

# Filters
OPS = [
    ("eq", 1),
    ("=", 1),
    ("neq", 2),
    ("!=", 2),
    ("gt", 3),
    (">", 3),
    ("gte", 4),
    (">=", 4),
    ("lt", 5),
    ("<", 5),
    ("lte", 6),
    ("<=", 6),
    ("eq", None),
    ("neq", None),
    ("is_null", None),
    ("is null", None),
    ("is_not_null", None),
    ("is not null", None),
    ("contains", "ab"),
    ("not_contains", "ab"),
    ("not contains", "ab"),
    ("starts_with", "ab"),
    ("startswith", "ab"),
    ("not_starts_with", "ab"),
    ("not startswith", "ab"),
    ("ends_with", "ab"),
    ("endswith", "ab"),
    ("not_ends_with", "ab"),
    ("not endswith", "ab"),
    ("like", "a%"),
    ("not_like", "a%"),
    ("not like", "a%"),
    ("ilike", "a%"),
    ("not_ilike", "a%"),
    ("not ilike", "a%"),
    ("in", [1, 2, 3]),
    ("in", "x, y,,z"),
    ("in", []),
    ("in", 7),
    ("in", [1, None]),
    ("in", [None]),
    ("in", {5}),
    ("not in", [1, 2]),
    ("not_in", []),
    ("not_in", [None]),
    ("not in", [1, None]),
    ("not_in", "q,r"),
    ("between", [1, 9]),
    ("not_between", [1, 9]),
    ("not between", [1, 9]),
    ("between", "1 AND 9"),
    ("between", "1,9"),
]
for i, (o, v) in enumerate(OPS):
    case(
        f"filter_{i:02d}_{o.replace(' ', '_')}",
        {"table": "users", "columns": ["id"], "filters": [_f("age", o, v)]},
    )
case(
    "filter_between_bad",
    {"table": "users", "columns": ["id"], "filters": [_f("age", "between", 3)]},
    validate_spec=False,
)
case(
    "filter_in_toomany",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [_f("age", "in", list(range(1001)))],
    },
    validate_spec=False,
)
case(
    "filter_unsupported_op",
    {"table": "users", "columns": ["id"], "filters": [_f("age", "zork", 1)]},
    validate_spec=False,
)
case(
    "filter_no_column",
    {"table": "users", "columns": ["id"], "filters": [{"op": "eq", "value": 1}]},
    validate_spec=False,
)
case(
    "filter_operator_key",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [{"column": "age", "operator": "GT", "value": 1}],
    },
)
case(
    "filter_default_op",
    {"table": "users", "columns": ["id"], "filters": [{"column": "age", "value": 1}]},
)
case(
    "filter_prefix",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            {"column": "age", "op": "eq", "value": 1, "tablePrefix": "users"},
            {"column": "age", "op": "eq", "value": 2, "table_prefix": "users"},
        ],
    },
)
case(
    "filter_or",
    {
        "table": "users",
        "columns": ["id"],
        "filter_join": "OR",
        "filters": [_f("age", "gt", 1), _f("age", "lt", 9)],
    },
)
case(
    "filter_join_bad",
    {
        "table": "users",
        "columns": ["id"],
        "filter_join": "XOR",
        "filters": [_f("age", "gt", 1), _f("age", "lt", 9)],
    },
)
case(
    "filter_combiner",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            _f("age", "gt", 1),
            _f("age", "lt", 9, combiner="or"),
            _f("age", "neq", 4, combiner="bogus"),
            _f("age", "neq", 5, combiner=3),
        ],
    },
)
case(
    "filter_parens",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            _f("age", "gt", 1, parenOpen=True),
            _f("age", "lt", 9, combiner="OR", parenClose=True),
            _f("status", "eq", "a", combiner="AND", parenOpen=2),
            _f("status", "eq", "b", combiner="OR", parenOpen="(("),
            _f("status", "eq", "c", parenClose=5),
            _f("status", "eq", "d", parenClose=")"),
            _f("status", "eq", "e", parenOpen=0, parenClose=0),
            _f("status", "eq", "f", parenOpen=99),
        ],
    },
)
case(
    "filter_unbalanced_close",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            _f("age", "gt", 1, parenClose=True),
            _f("age", "lt", 9, combiner="OR", parenClose="))"),
        ],
    },
)
case(
    "filter_open_left",
    {"table": "users", "columns": ["id"], "filters": [_f("age", "gt", 1, parenOpen=3)]},
)
case(
    "filter_enforced",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            _f("age", "gt", 1),
            _f("client_id", "eq", 7, _enforced=True),
            _f("status", "in", ["a", "b"], combiner="OR"),
            _f("client_id", "in", [8, 9], _enforced=True),
        ],
    },
)
case(
    "filter_enforced_only",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [_f("client_id", "eq", 7, _enforced=True)],
    },
)
case(
    "filter_subquery_in",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            _f("id", "in", None, subquery=_sub(filters=[_f("total", "gt", 5)]))
        ],
    },
)
case(
    "filter_subquery_not_in",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [_f("id", "not_in", _sub(limit=3))],
    },
)
case(
    "filter_subquery_cmp",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [_f("age", "gt", _sub(columns=[{"column": "total", "agg": "max"}]))],
    },
)
case(
    "filter_subquery_eq_null_value",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [_f("id", "eq", None, subquery=_sub())],
    },
)
case(
    "filter_exists",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [{"op": "exists", "subquery": _sub(filters=[_f("total", "gt", 1)])}],
    },
)
case(
    "filter_not_exists",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [
            {"op": "not exists", "value": _sub()},
            {"op": "not_exists", "subquery": _sub(), "column": "id"},
        ],
    },
)
case(
    "filter_exists_bad",
    {
        "table": "users",
        "columns": ["id"],
        "filters": [{"op": "exists", "column": "id", "value": 3}],
    },
    validate_spec=False,
)
case(
    "subquery_from",
    {
        "table": {
            "table": "orders",
            "columns": ["user_id", {"column": "total", "agg": "sum", "alias": "tot"}],
        },
        "columns": ["subquery.user_id"],
        "limit": 5,
    },
    validate_spec=False,
)
case(
    "subquery_from_filters",
    {
        "table": {
            "table": "orders",
            "columns": ["user_id"],
            "filters": [_f("total", "gt", 5)],
        },
        "columns": ["subquery.user_id"],
        "filters": [_f("user_id", "gt", 1, table="subquery")],
    },
    validate_spec=False,
)

# Tenant / user isolation
case(
    "user_filter",
    {"table": "users", "columns": ["id"]},
    user_id=7,
    force_user_filter=True,
)
case(
    "user_filter_join",
    {
        "table": "orders",
        "columns": ["orders.id", "users.email"],
        "joins": [{"table": "users"}],
    },
    user_id=7,
    force_user_filter=True,
    ownership_paths=OWNERSHIP,
)
case(
    "user_filter_nopath",
    {"table": "orders", "columns": ["id"]},
    user_id=7,
    force_user_filter=True,
)
case(
    "user_filter_nouser", {"table": "users", "columns": ["id"]}, force_user_filter=True
)
case("tenant_arg", {"table": "users", "columns": ["id"]}, tenant_id=42)
case("tenant_in_spec", {"table": "users", "columns": ["id"], "tenant_id": 11})
case("tenant_alt_col", {"table": "items", "columns": ["id"]}, tenant_id=42)
case(
    "tenant_noschema",
    {"table": "users", "columns": ["id"]},
    tenant_id="acme",
    schema=None,
)
case(
    "tenant_plus_user_filters",
    {"table": "users", "columns": ["id"], "filters": [_f("age", "gt", 3)]},
    tenant_id=1,
    user_id=2,
    force_user_filter=True,
)
case(
    "tenant_subquery_from",
    {
        "table": {"table": "orders", "columns": ["user_id"]},
        "columns": ["subquery.user_id"],
    },
    tenant_id=5,
    user_id=6,
    force_user_filter=True,
    validate_spec=False,
)

# Vector / hybrid
case(
    "vector",
    {
        "table": "users",
        "columns": ["id"],
        "vector_search": {"vector": [0.1, 0.2, 0.3], "column": "embedding", "top_k": 5},
    },
)
case(
    "vector_nodist",
    {
        "table": "users",
        "columns": ["id"],
        "vector_search": {"vector": [1, 2], "include_distances": False, "metric": "l2"},
    },
)
case(
    "vector_minscore",
    {
        "table": "users",
        "columns": ["id"],
        "vector_search": {
            "vector": [1, 2],
            "min_score": 0.5,
            "metric": "dot_product",
            "top_k": 3,
        },
        "limit": 50,
    },
)
case(
    "vector_order",
    {
        "table": "users",
        "columns": ["id"],
        "vector_search": {"vector": [1, 2]},
        "order_by": [{"column": "id"}],
    },
)
case(
    "vector_filters",
    {
        "table": "users",
        "columns": ["id"],
        "vector_search": {"vector": [1, 2], "min_score": 1},
        "filters": [_f("age", "gt", 3)],
        "offset": 2,
    },
)
case(
    "hybrid_rrf",
    {
        "table": "users",
        "columns": ["id"],
        "hybrid_search": {
            "vector": [0.1, 0.2],
            "query_text": "hello",
            "text_columns": ["name", "bio"],
            "top_k": 7,
        },
    },
)
case(
    "hybrid_linear",
    {
        "table": "users",
        "columns": ["id"],
        "hybrid_search": {
            "vector": [0.1, 0.2],
            "query_text": "hello",
            "text_columns": ["name"],
            "fusion": "linear",
            "alpha": 0.3,
        },
    },
)
case(
    "hybrid_noscores",
    {
        "table": "users",
        "columns": ["id"],
        "hybrid_search": {
            "vector": [1, 2],
            "text_columns": ["name"],
            "include_scores": False,
        },
    },
)
case(
    "hybrid_notext",
    {
        "table": "users",
        "columns": ["id"],
        "hybrid_search": {"vector": [1, 2], "include_scores": False},
    },
)
case(
    "hybrid_nocols_scores",
    {"table": "users", "columns": ["id"], "hybrid_search": {"vector": [1, 2]}},
)

# CTEs / set ops / metrics
case(
    "cte",
    {
        "table": "recent",
        "columns": ["recent.user_id"],
        "ctes": [
            {
                "name": "recent",
                "columns": ["user_id"],
                "query": {
                    "table": "orders",
                    "columns": ["user_id"],
                    "filters": [_f("total", "gt", 5)],
                },
            }
        ],
    },
)
case(
    "cte_recursive_materialized",
    {
        "table": "a",
        "columns": ["a.id"],
        "ctes": [
            {
                "name": "a",
                "recursive": True,
                "materialized": True,
                "query": {"table": "users", "columns": ["id"]},
            },
            {
                "name": "b",
                "materialized": False,
                "query": {"table": "orders", "columns": ["id"], "limit": 4},
            },
        ],
    },
)
case(
    "cte_join",
    {
        "table": "users",
        "columns": ["users.id", "big.total"],
        "ctes": [
            {
                "name": "big",
                "query": {"table": "orders", "columns": ["user_id", "total"]},
            }
        ],
        "joins": [
            {"table": "big", "on": [{"left": "users.id", "right": "big.user_id"}]}
        ],
    },
)
case(
    "cte_bad_query",
    {"table": "users", "columns": ["id"], "ctes": [{"name": "x", "query": "oops"}]},
    validate_spec=False,
)
case(
    "cte_bad_item",
    {"table": "users", "columns": ["id"], "ctes": ["oops"]},
    validate_spec=False,
)
case(
    "set_union",
    {
        "table": "users",
        "columns": ["id"],
        "set_operations": [
            {
                "operation": "union all",
                "query": {
                    "table": "users",
                    "columns": ["id"],
                    "filters": [_f("age", "gt", 3)],
                },
            }
        ],
    },
)
case(
    "set_multi",
    {
        "table": "users",
        "columns": ["id"],
        "set_operations": [
            {"query": {"table": "users", "columns": ["id"]}},
            {
                "operation": "intersect",
                "query": {"table": "users", "columns": ["id"], "limit": 2},
            },
            {"operation": "except", "query": {"table": "users", "columns": ["id"]}},
        ],
    },
)
case(
    "set_cte",
    {
        "table": "recent",
        "columns": ["recent.user_id"],
        "ctes": [
            {"name": "recent", "query": {"table": "orders", "columns": ["user_id"]}}
        ],
        "set_operations": [{"query": {"table": "users", "columns": ["id"]}}],
    },
)
case(
    "set_missing_query",
    {"table": "users", "columns": ["id"], "set_operations": [{"operation": "union"}]},
    validate_spec=False,
)
case(
    "set_bad_item",
    {"table": "users", "columns": ["id"], "set_operations": ["x"]},
    validate_spec=False,
)
case(
    "metrics_inline",
    {
        "table": "orders",
        "columns": ["status"],
        "metrics": [{"name": "rev", "sql_expression": "SUM(total)"}, "nope", 5],
    },
)
case(
    "metric_col_dict",
    {
        "table": "orders",
        "columns": [
            {
                "column": "total",
                "metric": {
                    "name": "avg_t",
                    "sql_expression": "AVG(total)",
                    "type": "avg",
                },
            }
        ],
    },
    validate_spec=False,
)
case(
    "semantic_models",
    {
        "table": "orders",
        "columns": ["status", {"column": "revenue"}],
        "metrics": ["revenue"],
    },
    semantic_models=[
        {
            "name": "orders_model",
            "table_name": "orders",
            "dimensions": [],
            "metrics": [{"name": "revenue", "sql_expression": "SUM(total)"}],
        }
    ],
)
case(
    "semantic_spec_inline",
    {
        "table": "orders",
        "columns": ["status"],
        "metrics": ["revenue"],
        "semantic_model": {
            "models": [
                {
                    "name": "m",
                    "table_name": "orders",
                    "metrics": [{"name": "revenue", "sql_expression": "SUM(total)"}],
                }
            ]
        },
    },
    validate_spec=False,
)

# Error / odd shapes
case("missing_table", {"columns": ["id"]}, validate_spec=False)
case("unknown_base_table", {"table": "ghost", "columns": ["id"]})
case("bad_col_ident", {"table": "users", "columns": ["id; drop"]}, validate_spec=False)
case("unknown_key", {"table": "users", "bogus": 1})
case(
    "unknown_key_allowed",
    {"table": "users", "columns": ["id"], "bogus": 1},
    allow_unknown_keys=True,
)
case(
    "capabilities_dict",
    {"table": "users", "columns": ["id"], "limit": 3, "order_by": [{"column": "id"}]},
    capabilities={"sorts": True},
)


class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _object_spec() -> _Obj:
    return _Obj(
        table="users",
        columns=["id", {"column": "age", "agg": "max"}],
        filters=[
            _Obj(column="age", op="gt", value=3),
            _Obj(column="status", op="eq", value="z"),
        ],
        having=[_Obj(column="age", agg="max", op="gt", value=1)],
        order_by=[_Obj(column="id", direction="desc")],
        joins=[],
        limit=9,
    )


def _dialects() -> list[str]:
    return list_dialects()


def _canon(value: Any) -> Any:
    return json.loads(json.dumps(value, default=repr, sort_keys=True))


def _run(name: str, spec: Any, kw: dict[str, Any], dialect: str) -> Any:
    kw = dict(kw)
    schema = SCHEMA if "schema" not in kw else kw.pop("schema")
    mw = kw.pop("middleware", None)
    try:
        comp = QueryCompiler(spec, schema=schema, dialect=dialect, middleware=mw, **kw)
        sql, params, csql, cparams = comp.compile()
        return {
            "sql": sql,
            "params": _canon(params),
            "count_sql": csql,
            "count_params": _canon(cparams),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _digest(rec: Any) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:20]


def _extra_cases() -> list[tuple[str, Any, dict[str, Any]]]:
    pre_post = MiddlewarePipeline()
    return [
        ("object_spec", _object_spec(), {}),
        (
            "middleware_empty",
            {"table": "users", "columns": ["id"]},
            {"middleware": pre_post},
        ),
    ]


def _build() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    all_cases = [(n, s, k) for n, s, k in CASES] + _extra_cases()
    for name, spec, kw in all_cases:
        row: dict[str, Any] = {}
        for d in _dialects():
            # specs are mutated by nothing, but object specs are re-used: rebuild
            sp = _object_spec() if name == "object_spec" else spec
            rec = _run(name, sp, kw, d)
            row[d] = rec if d in VERBATIM_DIALECTS else _digest(rec)
        out[name] = row
    return out


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_compile_matrix_matches_golden() -> None:
    built = _build()
    if os.environ.get("QB_UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        COMPILE_GOLDEN.write_text(
            json.dumps(built, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    golden = _load(COMPILE_GOLDEN)
    assert sorted(built) == sorted(golden)
    mismatches = [
        f"{n}[{d}]"
        for n in golden
        for d in golden[n]
        if built[n].get(d) != golden[n][d]
    ]
    assert not mismatches, f"{len(mismatches)} drifted: {mismatches[:25]}"


@pytest.mark.parametrize(
    "case_name",
    ["basic", "agg_all", "filter_parens", "window_functions", "cte", "vector"],
)
def test_golden_has_real_output(case_name: str) -> None:
    """Guards against a degenerate snapshot made only of errors."""
    golden = _load(COMPILE_GOLDEN)
    assert "sql" in golden[case_name]["postgres"]


def test_golden_covers_every_dialect() -> None:
    golden = _load(COMPILE_GOLDEN)
    assert set(golden["basic"]) == set(list_dialects())
    for d in list_dialects():
        get_dialect(d)


# ---------------------------------------------------------------- validation

INVALID_SPECS: list[tuple[str, Any, bool]] = [
    ("not_dict", [1], False),
    ("unknown_top", {"table": "t", "zzz": 1}, False),
    ("unknown_top_ok", {"table": "t", "zzz": 1}, True),
    ("no_table", {}, False),
    ("table_bad", {"table": "a b"}, False),
    ("table_nonstr", {"table": 5}, False),
    ("table_sub", {"table": {"table": "x", "columns": ["a b"]}}, False),
    ("columns_nonlist", {"table": "t", "columns": "id"}, False),
    ("columns_none", {"table": "t", "columns": None}, False),
    ("columns_toomany", {"table": "t", "columns": ["c"] * 101}, False),
    ("col_star_prefix", {"table": "t", "columns": ["t.*"]}, False),
    ("col_star_prefix_bad", {"table": "t", "columns": ["t;.*"]}, False),
    ("col_bad", {"table": "t", "columns": ["a b"]}, False),
    ("col_type", {"table": "t", "columns": [5]}, False),
    ("col_unknown_key", {"table": "t", "columns": [{"column": "a", "zz": 1}]}, False),
    ("col_unknown_key_ok", {"table": "t", "columns": [{"column": "a", "zz": 1}]}, True),
    ("col_noname", {"table": "t", "columns": [{"alias": "x"}]}, False),
    ("col_expr", {"table": "t", "columns": [{"expression": "1"}]}, False),
    ("col_name_nonstr", {"table": "t", "columns": [{"column": 4}]}, False),
    ("col_star_dict", {"table": "t", "columns": [{"column": "*"}]}, False),
    ("col_star_dict_prefix", {"table": "t", "columns": [{"column": "x.*"}]}, False),
    ("col_dict_prefix_bad", {"table": "t", "columns": [{"column": "x y.*"}]}, False),
    ("col_dict_bad", {"table": "t", "columns": [{"column": "x y"}]}, False),
    (
        "col_agg_bad",
        {"table": "t", "columns": [{"column": "a", "agg": "median"}]},
        False,
    ),
    (
        "col_alias_nonstr",
        {"table": "t", "columns": [{"column": "a", "alias": 3}]},
        False,
    ),
    (
        "col_alias_long",
        {"table": "t", "columns": [{"column": "a", "alias": "x" * 300}]},
        False,
    ),
    (
        "col_alias_nul",
        {"table": "t", "columns": [{"column": "a", "alias": "x\x00"}]},
        False,
    ),
    (
        "col_table_bad",
        {"table": "t", "columns": [{"column": "a", "table": "b c"}]},
        False,
    ),
    (
        "col_grain_bad",
        {"table": "t", "columns": [{"column": "a", "time_grain": "eon"}]},
        False,
    ),
    (
        "col_grain_ok",
        {"table": "t", "columns": [{"column": "a", "grain": "day"}]},
        False,
    ),
    ("cw_nondict", {"table": "t", "columns": [{"case_when": 5}]}, False),
    (
        "cw_nobranches",
        {"table": "t", "columns": [{"case_when": {"branches": []}}]},
        False,
    ),
    (
        "cw_branch_type",
        {"table": "t", "columns": [{"case_when": {"branches": [5]}}]},
        False,
    ),
    (
        "cw_no_cond",
        {"table": "t", "columns": [{"case_when": {"branches": [{"then_value": 1}]}}]},
        False,
    ),
    (
        "cw_obj",
        {
            "table": "t",
            "columns": [
                {"case_when": _Obj(branches=[_Obj(condition={"column": "a"})])}
            ],
        },
        False,
    ),
    ("metrics_nonlist", {"table": "t", "metrics": "x"}, False),
    ("joins_nonlist", {"table": "t", "joins": "x"}, False),
    ("joins_toomany", {"table": "t", "joins": [{"table": "u"}] * 21}, False),
    ("join_type", {"table": "t", "joins": [5]}, False),
    ("join_unknown_key", {"table": "t", "joins": [{"table": "u", "zz": 1}]}, False),
    ("join_notable", {"table": "t", "joins": [{"type": "left"}]}, False),
    ("join_table_bad", {"table": "t", "joins": [{"table": "a b"}]}, False),
    (
        "join_alias_bad",
        {"table": "t", "joins": [{"table": "u", "alias": "a b"}]},
        False,
    ),
    (
        "join_left_table_bad",
        {"table": "t", "joins": [{"table": "u", "left_table": "a b"}]},
        False,
    ),
    (
        "join_left_col_bad",
        {"table": "t", "joins": [{"table": "u", "left_col": "a b"}]},
        False,
    ),
    (
        "join_right_col_bad",
        {"table": "t", "joins": [{"table": "u", "right_col": "a b"}]},
        False,
    ),
    ("join_on_nonlist", {"table": "t", "joins": [{"table": "u", "on": "x"}]}, False),
    (
        "join_on_many",
        {
            "table": "t",
            "joins": [{"table": "u", "on": [{"left": "a", "right": "b"}] * 11}],
        },
        False,
    ),
    (
        "join_on_missing",
        {"table": "t", "joins": [{"table": "u", "on": [{"left": "a"}]}]},
        False,
    ),
    (
        "join_on_bad",
        {
            "table": "t",
            "joins": [{"table": "u", "on": [{"left": "a b", "right": "b"}]}],
        },
        False,
    ),
    (
        "join_on_bad_right",
        {
            "table": "t",
            "joins": [{"table": "u", "on": [{"left": "a", "right": "b c"}]}],
        },
        False,
    ),
    ("join_obj", {"table": "t", "joins": [_Obj(table="u")]}, False),
    ("filters_nonlist", {"table": "t", "filters": "x"}, False),
    ("filters_toomany", {"table": "t", "filters": [{"column": "a"}] * 51}, False),
    ("filter_type", {"table": "t", "filters": [5]}, False),
    (
        "filter_unknown_key",
        {"table": "t", "filters": [{"column": "a", "zz": 1}]},
        False,
    ),
    (
        "filter_op_bad",
        {"table": "t", "filters": [{"column": "a", "op": "zork"}]},
        False,
    ),
    (
        "filter_sub_bad",
        {
            "table": "t",
            "filters": [{"column": "a", "op": "in", "subquery": {"table": "a b"}}],
        },
        False,
    ),
    (
        "filter_sub_col_bad",
        {
            "table": "t",
            "filters": [{"column": "a b", "op": "in", "subquery": {"table": "u"}}],
        },
        False,
    ),
    (
        "filter_sub_val",
        {
            "table": "t",
            "filters": [{"column": "a", "op": "in", "value": {"table": "u"}}],
        },
        False,
    ),
    (
        "filter_sub_obj",
        {
            "table": "t",
            "filters": [{"column": "a", "op": "in", "value": _Obj(table="u")}],
        },
        False,
    ),
    ("filter_exists_nosub", {"table": "t", "filters": [{"op": "exists"}]}, False),
    ("filter_nocol", {"table": "t", "filters": [{"op": "eq", "value": 1}]}, False),
    ("filter_col_bad", {"table": "t", "filters": [{"column": "a b"}]}, False),
    (
        "filter_prefix_bad",
        {"table": "t", "filters": [{"column": "a", "table": "b c"}]},
        False,
    ),
    (
        "filter_in_many",
        {
            "table": "t",
            "filters": [{"column": "a", "op": "in", "value": list(range(1001))}],
        },
        False,
    ),
    (
        "filter_in_str_many",
        {
            "table": "t",
            "filters": [{"column": "a", "op": "in", "value": ",".join(["x"] * 1001)}],
        },
        False,
    ),
    (
        "filter_in_ok",
        {"table": "t", "filters": [{"column": "a", "op": "in", "value": "x,y"}]},
        False,
    ),
    (
        "filter_between_len",
        {"table": "t", "filters": [{"column": "a", "op": "between", "value": [1]}]},
        False,
    ),
    (
        "filter_between_str",
        {
            "table": "t",
            "filters": [{"column": "a", "op": "not_between", "value": "oneword"}],
        },
        False,
    ),
    (
        "filter_between_ok",
        {"table": "t", "filters": [{"column": "a", "op": "between", "value": [1, 2]}]},
        False,
    ),
    (
        "filter_obj",
        {"table": "t", "filters": [_Obj(column="a", op="eq", value=1)]},
        False,
    ),
    ("filter_join_type", {"table": "t", "filter_join": 3}, False),
    ("having_nonlist", {"table": "t", "having": "x"}, False),
    ("having_toomany", {"table": "t", "having": [{"column": "a"}] * 21}, False),
    ("having_type", {"table": "t", "having": [5]}, False),
    ("having_unknown_key", {"table": "t", "having": [{"column": "a", "zz": 1}]}, False),
    ("having_nocol", {"table": "t", "having": [{"agg": "sum"}]}, False),
    ("having_col_bad", {"table": "t", "having": [{"column": "a b"}]}, False),
    ("having_star", {"table": "t", "having": [{"column": "*"}]}, False),
    ("having_agg_bad", {"table": "t", "having": [{"column": "a", "agg": "zz"}]}, False),
    ("having_op_bad", {"table": "t", "having": [{"column": "a", "op": "zz"}]}, False),
    ("having_obj", {"table": "t", "having": [_Obj(column="a")]}, False),
    ("order_nonlist", {"table": "t", "order_by": "x"}, False),
    ("order_toomany", {"table": "t", "order_by": [{"column": "a"}] * 21}, False),
    ("order_type", {"table": "t", "order_by": [5]}, False),
    (
        "order_unknown_key",
        {"table": "t", "order_by": [{"column": "a", "zz": 1}]},
        False,
    ),
    ("order_nocol", {"table": "t", "order_by": [{"direction": "asc"}]}, False),
    ("order_col_bad", {"table": "t", "order_by": [{"column": "a b"}]}, False),
    (
        "order_pfx_bad",
        {"table": "t", "order_by": [{"column": "a", "tablePrefix": "b c"}]},
        False,
    ),
    ("order_obj", {"table": "t", "order_by": [_Obj(column="a")]}, False),
    ("limit_nonint", {"table": "t", "limit": "abc"}, False),
    ("limit_none", {"table": "t", "limit": None}, False),
    ("limit_neg", {"table": "t", "limit": -1}, False),
    ("limit_big", {"table": "t", "limit": 10001}, False),
    ("offset_nonint", {"table": "t", "offset": "abc"}, False),
    ("offset_neg", {"table": "t", "offset": -1}, False),
    ("offset_big", {"table": "t", "offset": 1_000_001}, False),
    ("distinct_type", {"table": "t", "distinct": "yes"}, False),
    ("vs_type", {"table": "t", "vector_search": 5}, False),
    (
        "vs_unknown_key",
        {"table": "t", "vector_search": {"vector": [1], "zz": 1}},
        False,
    ),
    (
        "vs_unknown_key_ok",
        {"table": "t", "vector_search": {"vector": [1], "zz": 1}},
        True,
    ),
    ("vs_vec_empty", {"table": "t", "vector_search": {"vector": []}}, False),
    ("vs_vec_nonnum", {"table": "t", "vector_search": {"vector": ["a"]}}, False),
    ("vs_vec_bool", {"table": "t", "vector_search": {"vector": [True]}}, False),
    (
        "vs_col_bad",
        {"table": "t", "vector_search": {"vector": [1], "column": "a b"}},
        False,
    ),
    (
        "vs_topk_bad",
        {"table": "t", "vector_search": {"vector": [1], "top_k": 0}},
        False,
    ),
    (
        "vs_topk_str",
        {"table": "t", "vector_search": {"vector": [1], "top_k": "3"}},
        False,
    ),
    (
        "vs_metric_bad",
        {"table": "t", "vector_search": {"vector": [1], "metric": "manhattan"}},
        False,
    ),
    (
        "vs_minscore_bad",
        {"table": "t", "vector_search": {"vector": [1], "min_score": "x"}},
        False,
    ),
    (
        "vs_ok",
        {"table": "t", "vector_search": {"vector": [1, 2.5], "min_score": 0.3}},
        False,
    ),
    ("vs_obj", {"table": "t", "vector_search": _Obj(vector=[1], top_k=3)}, False),
    ("vs_obj_bad", {"table": "t", "vector_search": _Obj(vector=[])}, False),
    ("hs_type", {"table": "t", "hybrid_search": 5}, False),
    (
        "hs_unknown_key",
        {"table": "t", "hybrid_search": {"vector": [1], "zz": 1}},
        False,
    ),
    ("hs_vec_empty", {"table": "t", "hybrid_search": {"vector": []}}, False),
    ("hs_vec_nonnum", {"table": "t", "hybrid_search": {"vector": ["a"]}}, False),
    (
        "hs_vcol_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "vector_column": "a b"}},
        False,
    ),
    (
        "hs_qtext_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "query_text": 4}},
        False,
    ),
    (
        "hs_tcols_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "text_columns": "a"}},
        False,
    ),
    (
        "hs_tcol_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "text_columns": ["a b"]}},
        False,
    ),
    (
        "hs_alpha_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "alpha": 2}},
        False,
    ),
    (
        "hs_alpha_type",
        {"table": "t", "hybrid_search": {"vector": [1], "alpha": "x"}},
        False,
    ),
    (
        "hs_fusion_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "fusion": "zz"}},
        False,
    ),
    ("hs_rrf_bad", {"table": "t", "hybrid_search": {"vector": [1], "rrf_k": 0}}, False),
    (
        "hs_topk_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "top_k": 20000}},
        False,
    ),
    (
        "hs_metric_bad",
        {"table": "t", "hybrid_search": {"vector": [1], "metric": "zz"}},
        False,
    ),
    (
        "hs_ok",
        {"table": "t", "hybrid_search": {"vector": [1], "text_columns": ["a"]}},
        False,
    ),
    (
        "hs_obj",
        {"table": "t", "hybrid_search": _Obj(vector=[1], query_text="q")},
        False,
    ),
    ("hs_obj_bad", {"table": "t", "hybrid_search": _Obj(vector=[1], alpha=9)}, False),
    ("ctes_nonlist", {"table": "t", "ctes": "x"}, False),
    (
        "ctes_bad",
        {"table": "t", "ctes": [{"name": "a b", "query": {"table": "t"}}]},
        False,
    ),
    (
        "ctes_ok",
        {"table": "t", "ctes": [{"name": "a", "query": {"table": "t"}}]},
        False,
    ),
    ("wf_nonlist", {"table": "t", "window_functions": "x"}, False),
    (
        "wf_bad",
        {"table": "t", "window_functions": [{"function": "zzz_not_a_func"}]},
        False,
    ),
    ("wf_ok", {"table": "t", "window_functions": [{"function": "row_number"}]}, False),
    ("so_nonlist", {"table": "t", "set_operations": "x"}, False),
    ("so_item", {"table": "t", "set_operations": [5]}, False),
    (
        "so_op_bad",
        {
            "table": "t",
            "set_operations": [{"operation": "zip", "query": {"table": "t"}}],
        },
        False,
    ),
    ("so_noquery", {"table": "t", "set_operations": [{"operation": "union"}]}, False),
    (
        "so_query_bad",
        {"table": "t", "set_operations": [{"query": {"table": "a b"}}]},
        False,
    ),
    (
        "so_query_obj",
        {"table": "t", "set_operations": [{"query": _Obj(table="a b")}]},
        False,
    ),
    (
        "so_obj",
        {
            "table": "t",
            "set_operations": [_Obj(operation="union", query={"table": "u"})],
        },
        False,
    ),
    ("gt_bad", {"table": "t", "grouping_type": "zz"}, False),
    ("gt_ok", {"table": "t", "grouping_type": " Rollup "}, False),
    ("gs_bad", {"table": "t", "grouping_sets": "x"}, False),
    ("gs_obj", {"table": "t", "grouping_sets": _Obj(sets=[["a"]])}, False),
    ("rollup_bad", {"table": "t", "rollup": "x"}, False),
    ("rollup_obj", {"table": "t", "rollup": _Obj(columns=["a"])}, False),
    ("cube_bad", {"table": "t", "cube": "x"}, False),
    ("cube_list", {"table": "t", "cube": ["a"]}, False),
    ("pivot_bad", {"table": "t", "pivot": "x"}, False),
    ("pivot_obj", {"table": "t", "pivot": _Obj(column="a")}, False),
    ("pivot_dict", {"table": "t", "pivot": {}}, False),
    ("order_of_errors_1", {"table": "a b", "columns": "x", "zz": 1}, False),
    (
        "order_of_errors_2",
        {"table": "t", "columns": "x", "joins": "y", "limit": "z"},
        False,
    ),
    (
        "order_of_errors_3",
        {"table": "t", "joins": "y", "filters": "x", "having": "q"},
        False,
    ),
    (
        "order_of_errors_4",
        {
            "table": "t",
            "limit": "z",
            "offset": "z",
            "distinct": 1,
            "grouping_type": "q",
        },
        False,
    ),
    (
        "order_of_errors_5",
        {"table": "t", "offset": "z", "distinct": 1, "vector_search": 3, "ctes": 3},
        False,
    ),
]


def _validate_all() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, spec, allow in INVALID_SPECS:
        try:
            validate_query_spec(spec, allow_unknown_keys=allow)
            out[name] = "OK"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"{type(exc).__name__}: {exc}"
    return out


def test_validate_query_spec_matches_golden() -> None:
    got = _validate_all()
    if os.environ.get("QB_UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        VALIDATE_GOLDEN.write_text(
            json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    golden = _load(VALIDATE_GOLDEN)
    assert got == golden


def test_validate_golden_has_both_outcomes() -> None:
    golden = _load(VALIDATE_GOLDEN)
    assert any(v == "OK" for v in golden.values())
    assert sum(v.startswith("ValidationError") for v in golden.values()) > 100
