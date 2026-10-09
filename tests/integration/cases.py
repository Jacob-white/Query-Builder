"""
Declarative conformance cases: a QuerySpec plus the rows it MUST return on every
engine seeded with ``dataset`` (expected values are hand-derived from the data,
not produced by the code under test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from tests.integration.dataset import (
    T_DEPT,
    T_EMP,
    T_MIXED,
    T_RES,
)


@dataclass
class Case:
    id: str
    spec: dict[str, Any]
    expected: list[dict[str, Any]]
    ordered: bool = True
    requires: tuple[str, ...] = ()
    expected_count: int | None = None  # total rows ignoring limit/offset
    float_keys: tuple[str, ...] = ()
    group: str = "query"
    extra: dict[str, Any] = field(default_factory=dict)


def norm(value: Any) -> Any:
    """Normalise driver-specific value types so engines compare equal."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return int(value) if value == int(value) else round(value, 4)
    if isinstance(value, bytes):
        return value.decode()
    return value


def norm_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(k).lower(): norm(v) for k, v in r.items()} for r in rows]


def _ids(*ids: int) -> list[dict[str, Any]]:
    return [{"id": i} for i in ids]


def _emp(columns: list[Any] | None = None, **kw: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "table": T_EMP,
        "columns": columns or ["id"],
        "order_by": [{"column": "id", "direction": "asc"}],
        "limit": 50,
    }
    spec.update(kw)
    return spec


def _flt(column: str, op: str, value: Any = None) -> dict[str, Any]:
    return _emp(filters=[{"column": column, "op": op, "value": value}])


CASES: list[Case] = []


def add(case: Case) -> None:
    CASES.append(case)


# ---------------------------------------------------------------- projection
add(
    Case(
        "select-projection",
        _emp(["id", "name"], limit=3),
        [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Carol"},
        ],
        expected_count=8,
        group="select",
    )
)
add(
    Case(
        "select-all-rows-with-null",
        _emp(["id", "email"], limit=50),
        [
            {"id": 1, "email": "alice@example.com"},
            {"id": 2, "email": None},
            {"id": 3, "email": "carol@example.com"},
            {"id": 4, "email": None},
            {"id": 5, "email": "eve@example.com"},
            {"id": 6, "email": None},
            {"id": 7, "email": "ob@example.com"},
            {"id": 8, "email": "zoe@example.com"},
        ],
        expected_count=8,
        group="null",
    )
)

# -------------------------------------------------------------------- filters
_FILTERS: list[tuple[str, str, str, Any, list[int]]] = [
    # id, column, op, value, expected ids
    ("eq", "name", "eq", "Dave", [4]),
    ("eq-symbol", "name", "=", "Dave", [4]),
    ("neq", "dept_id", "neq", 1, [3, 4, 5, 8]),  # NULL dept never matches !=
    ("gt", "salary", "gt", 100, [1, 7]),
    ("gte", "salary", "gte", 100, [1, 2, 7]),
    ("lt", "salary", "lt", 70, [6]),
    ("lte", "salary", "lte", 70, [5, 6]),
    ("contains", "name", "contains", "AL", [1]),  # case-insensitive
    ("starts-with", "name", "starts_with", "c", [3]),
    ("ends-with", "name", "ends_with", "E", [1, 4, 5]),
    ("like", "name", "like", "Dav%", [4]),
    ("ilike", "name", "ilike", "dAvE", [4]),
    ("not-like", "name", "not_like", "A%", [2, 3, 4, 5, 6, 7, 8]),
    ("not-contains", "name", "not_contains", "o", [1, 4, 5, 6]),
    ("not-starts-with", "name", "not_starts_with", "a", [2, 3, 4, 5, 6, 7, 8]),
    ("not-ends-with", "name", "not_ends_with", "e", [2, 3, 6, 7, 8]),
    ("in", "id", "in", [1, 3, 5], [1, 3, 5]),
    ("in-strings", "name", "in", ["Alice", "O'Brien", "nobody"], [1, 7]),
    ("not-in", "id", "not_in", [1, 3, 5], [2, 4, 6, 7, 8]),
    ("in-empty", "id", "in", [], []),
    ("between", "salary", "between", [70, 90], [3, 4, 5, 8]),
    ("not-between", "salary", "not_between", [70, 90], [1, 2, 6, 7]),
    ("is-null", "email", "is_null", None, [2, 4, 6]),
    ("is-not-null", "email", "is_not_null", None, [1, 3, 5, 7, 8]),
    ("eq-none-is-null", "email", "eq", None, [2, 4, 6]),
    ("neq-none-is-not-null", "email", "neq", None, [1, 3, 5, 7, 8]),
    ("apostrophe-value", "name", "eq", "O'Brien", [7]),
    ("unicode-value", "name", "eq", "Zoë Ünï", [8]),
]
for _id, _col, _op, _val, _ids_expected in _FILTERS:
    add(
        Case(
            f"filter-{_id}",
            _flt(_col, _op, _val),
            _ids(*_ids_expected),
            group="filter",
        )
    )

add(
    Case(
        "filter-and",
        _emp(
            filters=[
                {"column": "dept_id", "op": "eq", "value": 1},
                {"column": "salary", "op": "gt", "value": 100},
            ]
        ),
        _ids(1, 7),
        group="filter",
    )
)
add(
    Case(
        "filter-or",
        _emp(
            filters=[
                {"column": "name", "op": "eq", "value": "Alice"},
                {"column": "name", "op": "eq", "value": "Eve"},
            ],
            filter_join="OR",
        ),
        _ids(1, 5),
        group="filter",
    )
)
add(
    Case(
        "filter-in-subquery",
        _emp(
            filters=[
                {
                    "column": "dept_id",
                    "op": "in",
                    "value": {
                        "table": T_DEPT,
                        "columns": ["id"],
                        "filters": [{"column": "name", "op": "eq", "value": "Sales"}],
                    },
                }
            ]
        ),
        _ids(3, 4),
        group="filter",
    )
)

# ------------------------------------------------------------------------ joins
_JOIN_INNER = {
    "type": "inner",
    "table": T_DEPT,
    "on": [{"left": f"{T_EMP}.dept_id", "right": f"{T_DEPT}.id"}],
}
_JOIN_COLS = [
    {"column": "id", "table": T_EMP, "alias": "id"},
    {"column": "name", "table": T_DEPT, "alias": "dept"},
]
add(
    Case(
        "join-inner",
        _emp(_JOIN_COLS, joins=[_JOIN_INNER]),
        [
            {"id": 1, "dept": "Engineering"},
            {"id": 2, "dept": "Engineering"},
            {"id": 3, "dept": "Sales"},
            {"id": 4, "dept": "Sales"},
            {"id": 5, "dept": "Marketing"},
            {"id": 7, "dept": "Engineering"},
            {"id": 8, "dept": "Marketing"},
        ],
        expected_count=7,
        group="join",
    )
)
add(
    Case(
        "join-left",
        _emp(_JOIN_COLS, joins=[{**_JOIN_INNER, "type": "left"}]),
        [
            {"id": 1, "dept": "Engineering"},
            {"id": 2, "dept": "Engineering"},
            {"id": 3, "dept": "Sales"},
            {"id": 4, "dept": "Sales"},
            {"id": 5, "dept": "Marketing"},
            {"id": 6, "dept": None},
            {"id": 7, "dept": "Engineering"},
            {"id": 8, "dept": "Marketing"},
        ],
        expected_count=8,
        group="join",
    )
)
add(
    Case(
        "join-right",
        {
            "table": T_EMP,
            "columns": [
                {"column": "name", "table": T_DEPT, "alias": "dept"},
                {"column": "id", "table": T_EMP, "alias": "id"},
            ],
            "joins": [{**_JOIN_INNER, "type": "right"}],
            "filters": [
                {"column": "name", "table": T_DEPT, "op": "eq", "value": "Empty"}
            ],
            "limit": 50,
        },
        [{"dept": "Empty", "id": None}],
        requires=("right_join",),
        group="join",
    )
)
add(
    Case(
        "join-with-filter-and-order",
        {
            "table": T_EMP,
            "columns": _JOIN_COLS,
            "joins": [_JOIN_INNER],
            "filters": [
                {"column": "name", "table": T_DEPT, "op": "eq", "value": "Sales"}
            ],
            "order_by": [{"column": "id", "table": T_EMP, "direction": "desc"}],
            "limit": 50,
        },
        [{"id": 4, "dept": "Sales"}, {"id": 3, "dept": "Sales"}],
        group="join",
    )
)

# ------------------------------------------------------------ aggregate / group
_GROUPED_COLS = [
    {"column": "dept_id", "alias": "dept_id"},
    {"column": "id", "agg": "count", "alias": "n"},
    {"column": "salary", "agg": "sum", "alias": "total"},
]
_GROUPED = [
    {"dept_id": 1, "n": 3, "total": 330},
    {"dept_id": 2, "n": 2, "total": 170},
    {"dept_id": 3, "n": 2, "total": 145},
    {"dept_id": None, "n": 1, "total": 60},
]
add(
    Case(
        "group-by-count-sum",
        {"table": T_EMP, "columns": _GROUPED_COLS, "limit": 50},
        _GROUPED,
        ordered=False,
        group="aggregate",
    )
)
add(
    Case(
        "group-having",
        {
            "table": T_EMP,
            "columns": _GROUPED_COLS,
            "having": [{"column": "salary", "agg": "sum", "op": "gt", "value": 150}],
            "limit": 50,
        },
        [r for r in _GROUPED if r["total"] > 150],
        ordered=False,
        group="aggregate",
    )
)
add(
    Case(
        "aggregate-min-max-avg",
        {
            "table": T_EMP,
            "columns": [
                {"column": "salary", "agg": "min", "alias": "lo"},
                {"column": "salary", "agg": "max", "alias": "hi"},
                {"column": "salary", "agg": "avg", "alias": "mean"},
            ],
            "limit": 50,
        },
        [{"lo": 60, "hi": 120, "mean": 88.125}],
        group="aggregate",
    )
)
add(
    Case(
        "aggregate-null-handling",
        {
            "table": T_EMP,
            "columns": [
                {"column": "id", "agg": "count", "alias": "all_rows"},
                {"column": "email", "agg": "count", "alias": "with_email"},
                {"column": "dept_id", "agg": "count_distinct", "alias": "depts"},
            ],
            "limit": 50,
        },
        [{"all_rows": 8, "with_email": 5, "depts": 3}],
        group="null",
    )
)

# ------------------------------------------------------- order / limit / offset
add(
    Case(
        "order-desc-limit-offset",
        _emp(
            order_by=[{"column": "salary", "direction": "desc"}],
            limit=3,
            offset=1,
        ),
        _ids(7, 2, 3),
        expected_count=8,
        group="order",
    )
)
add(
    Case(
        "order-multi-key",
        _emp(
            filters=[{"column": "dept_id", "op": "is_not_null"}],
            order_by=[
                {"column": "dept_id", "direction": "asc"},
                {"column": "salary", "direction": "desc"},
            ],
        ),
        _ids(1, 7, 2, 3, 4, 8, 5),
        group="order",
    )
)
add(
    Case(
        "offset-past-end",
        _emp(limit=5, offset=100),
        [],
        expected_count=8,
        group="order",
    )
)
add(
    Case(
        "limit-zero-one",
        _emp(limit=1),
        _ids(1),
        expected_count=8,
        group="order",
    )
)

# -------------------------------------------------------- distinct / cte / window
add(
    Case(
        "distinct",
        _emp(
            ["dept_id"],
            filters=[{"column": "dept_id", "op": "is_not_null"}],
            distinct=True,
            order_by=[{"column": "dept_id", "direction": "asc"}],
        ),
        [{"dept_id": 1}, {"dept_id": 2}, {"dept_id": 3}],
        group="distinct",
    )
)
add(
    Case(
        "cte",
        {
            "table": "high_paid",
            "ctes": [
                {
                    "name": "high_paid",
                    "query": {
                        "table": T_EMP,
                        "columns": ["id", "salary"],
                        "filters": [{"column": "salary", "op": "gt", "value": 90}],
                    },
                }
            ],
            "columns": ["id"],
            "order_by": [{"column": "id", "direction": "asc"}],
            "limit": 50,
        },
        _ids(1, 2, 7),
        group="cte",
    )
)
add(
    Case(
        "window-row-number-and-partition-sum",
        {
            "table": T_EMP,
            "columns": ["id"],
            "window_functions": [
                {
                    "function": "ROW_NUMBER",
                    "partition_by": ["dept_id"],
                    "order_by": [{"column": "salary", "direction": "desc"}],
                    "alias": "rn",
                },
                {
                    "function": "SUM",
                    "arguments": ["salary"],
                    "partition_by": ["dept_id"],
                    "alias": "dept_total",
                },
            ],
            "order_by": [{"column": "id", "direction": "asc"}],
            "limit": 50,
        },
        [
            {"id": 1, "rn": 1, "dept_total": 330},
            {"id": 2, "rn": 3, "dept_total": 330},
            {"id": 3, "rn": 1, "dept_total": 170},
            {"id": 4, "rn": 2, "dept_total": 170},
            {"id": 5, "rn": 2, "dept_total": 145},
            {"id": 6, "rn": 1, "dept_total": 60},
            {"id": 7, "rn": 2, "dept_total": 330},
            {"id": 8, "rn": 1, "dept_total": 145},
        ],
        requires=("window",),
        group="window",
    )
)

# ---------------------------------------------- injection-looking bound values
_EVIL = [
    ("drop-table", "'; DROP TABLE qbit_employees; --"),
    ("or-true", "x' OR '1'='1"),
    ("union", "x' UNION SELECT name FROM qbit_departments --"),
    ("comment", "Alice'/*"),
    ("backslash", "\\'; DELETE FROM qbit_employees; --"),
    ("percent", "%"),
    ("semicolon", "a;b"),
]
for _id, _val in _EVIL:
    add(
        Case(
            f"binding-eq-{_id}",
            _flt("name", "eq", _val),
            [],
            group="binding",
        )
    )
add(
    Case(
        "binding-in-mixed",
        _flt("name", "in", ["Alice", "1; DELETE FROM qbit_employees"]),
        _ids(1),
        group="binding",
    )
)
add(
    Case(
        "binding-contains-quote",
        _flt("name", "contains", "'; --"),
        [],
        group="binding",
    )
)
add(
    Case(
        "binding-contains-literal-percent",
        _flt("name", "contains", "%"),
        [],
        group="binding",
    )
)
add(
    Case(
        "binding-contains-literal-underscore",
        _flt("name", "contains", "_"),
        [],
        group="binding",
    )
)

# ------------------------------------------------------------ identifier quoting
_RES_COLS = ["id", "select", "group", "order", "MixedCase"]
add(
    Case(
        "quoting-reserved-words-mixed-case",
        {
            "table": T_RES,
            "columns": _RES_COLS,
            "order_by": [{"column": "order", "direction": "asc"}],
            "limit": 50,
        },
        [
            dict(zip(_RES_COLS, (3, 30, "g1", 1, "Mc3"), strict=True)),
            dict(zip(_RES_COLS, (2, 20, "g2", 2, "Mc2"), strict=True)),
            dict(zip(_RES_COLS, (1, 10, "g1", 3, "Mc1"), strict=True)),
        ],
        group="quoting",
    )
)
add(
    Case(
        "quoting-reserved-filter",
        {
            "table": T_RES,
            "columns": ["id"],
            "filters": [{"column": "group", "op": "eq", "value": "g1"}],
            "order_by": [{"column": "select", "direction": "desc"}],
            "limit": 50,
        },
        _ids(3, 1),
        group="quoting",
    )
)
add(
    Case(
        "quoting-mixed-case-table",
        {"table": T_MIXED, "columns": ["id", "val"], "limit": 5},
        [{"id": 1, "val": "mixed"}],
        requires=("case_sensitive_identifiers",),
        group="quoting",
    )
)
