"""
Declarative Query Compiler for SQL Explorer & Query Builder.
============================================================
Compiles declarative JSON query specifications into safe, parameterized SQL
with multi-dialect support (PostgreSQL, Snowflake, MSSQL, SQLite, MySQL),
automatic identifier quoting, tenant isolation injection, join resolution,
derived GROUP BY, HAVING, ordering, and pagination.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from query_builder.dialects import IDENTIFIER_REGEX, BaseDialect, get_dialect
from query_builder.exceptions import (
    CompilationError,
    SecurityError,
    ValidationError,
)
from query_builder.join_solver import find_best_join_condition
from query_builder.models import SchemaSnapshot
from query_builder.security import (
    AliasCounter,
    resolve_ownership_predicate,
)

MAX_OFFSET = 1_000_000
MAX_LIMIT = 10_000
MAX_PROJECTIONS = 100
MAX_JOINS = 20
MAX_FILTERS = 50
MAX_HAVING = 20
MAX_ORDER_BY = 20
#: Longest text ``QueryCompiler.compile_search`` accepts.
MAX_SEARCH_TERM = 200

#: The type a value is cast to before it is searched as text, per dialect. A dialect not listed has no search.
SEARCH_CAST_TYPES: dict[str, str] = {
    **dict.fromkeys(
        (
            "postgres",
            "postgresql",
            "sqlite",
            "duckdb",
            "cockroach",
            "cockroachdb",
            "alloydb",
            "redshift",
        ),
        "TEXT",
    ),
    **dict.fromkeys(
        ("mysql", "mariadb", "tidb", "singlestore", "doris", "starrocks", "oceanbase"),
        "CHAR",
    ),
}

MAX_IN_VALUES = 1000

ALLOWED_SPEC_KEYS = {
    "table",
    "columns",
    "joins",
    "filters",
    "filter_join",
    "having",
    "order_by",
    "limit",
    "offset",
    "distinct",
    "tenant_id",
    "vector_search",
    "hybrid_search",
    "ctes",
    "window_functions",
    "metrics",
    "semantic_model",
    "semantic_models",
    "set_operations",
    "grouping_type",
    "grouping_sets",
    "rollup",
    "cube",
    "pivot",
}

ALLOWED_COLUMN_KEYS = {
    "column",
    "name",
    "agg",
    "aggregate",
    "alias",
    "table",
    "tablePrefix",
    "table_prefix",
    "distinct",
    "time_grain",
    "timeGrain",
    "grain",
    "metric",
    "format",
    "case_when",
    "expression",
    "raw_expression",
    "dimension",
    "masked",
    "masking_strategy",
}
ALLOWED_JOIN_KEYS = {
    "table",
    "type",
    "on",
    "left_table",
    "leftTable",
    "left_col",
    "leftCol",
    "right_col",
    "rightCol",
    "id",
    "alias",
}
ALLOWED_FILTER_KEYS = {
    "column",
    "op",
    "operator",
    "value",
    "subquery",
    "tablePrefix",
    "table_prefix",
    "table",
    "id",
    "combiner",
    "parenOpen",
    "parenClose",
    "paren_open",
    "paren_close",
    "_enforced",
}
ALLOWED_HAVING_KEYS = {
    "column",
    "agg",
    "aggregate",
    "op",
    "operator",
    "value",
    "table",
    "table_prefix",
    "tablePrefix",
    "id",
}
ALLOWED_ORDER_BY_KEYS = {
    "column",
    "direction",
    "nulls",
    "tablePrefix",
    "table_prefix",
    "table",
    "id",
}

AGGREGATE_MAP = {
    "count": "COUNT({})",
    "count_distinct": "COUNT(DISTINCT {})",
    "sum": "SUM({})",
    "avg": "AVG({})",
    "min": "MIN({})",
    "max": "MAX({})",
}

#: window functions whose value is the same for every row of a partition (no ORDER BY needed)
_WHOLE_PARTITION_AGGREGATES = frozenset({"SUM", "AVG", "COUNT", "MIN", "MAX"})

OPERATOR_MAP = {
    "eq": "=",
    "=": "=",
    "neq": "!=",
    "!=": "!=",
    "gt": ">",
    ">": ">",
    "gte": ">=",
    ">=": ">=",
    "lt": "<",
    "<": "<",
    "lte": "<=",
    "<=": "<=",
}

ALLOWED_FILTER_OPS = {
    "eq",
    "=",
    "neq",
    "!=",
    "gt",
    ">",
    "gte",
    ">=",
    "lt",
    "<",
    "lte",
    "<=",
    "is_null",
    "is null",
    "is_not_null",
    "is not null",
    "contains",
    "starts_with",
    "startswith",
    "ends_with",
    "endswith",
    "like",
    "ilike",
    "in",
    "not in",
    "not_in",
    "between",
    "not_like",
    "not like",
    "not_ilike",
    "not ilike",
    "not_contains",
    "not contains",
    "not_starts_with",
    "not startswith",
    "not_ends_with",
    "not endswith",
    "not_between",
    "not between",
    "exists",
    "not_exists",
    "not exists",
}

_BUILTIN_FILTER_OPS = set(ALLOWED_FILTER_OPS)
_CUSTOM_FILTER_OPERATORS: dict[str, Callable[..., Any]] = {}
_CUSTOM_FILTER_OPERATORS_LOCK = threading.RLock()


def register_filter_operator(
    name: str,
    handler: Callable[..., Any],
) -> None:
    """
    Register a custom filter operator handler.

    The handler should accept (quoted_ref: str, val: Any, dialect: BaseDialect)
    and return either a SQL clause string, or a tuple of (clause_str, params).
    """
    clean_name = name.lower().strip()
    with _CUSTOM_FILTER_OPERATORS_LOCK:
        _CUSTOM_FILTER_OPERATORS[clean_name] = handler
        ALLOWED_FILTER_OPS.add(clean_name)


def unregister_filter_operator(name: str) -> None:
    """
    Unregister a custom filter operator.
    """
    clean_name = name.lower().strip()
    with _CUSTOM_FILTER_OPERATORS_LOCK:
        _CUSTOM_FILTER_OPERATORS.pop(clean_name, None)
        if clean_name not in _BUILTIN_FILTER_OPS:
            ALLOWED_FILTER_OPS.discard(clean_name)


def list_filter_operators() -> list[str]:
    """
    Return a sorted list of all allowed filter operator names (built-in and custom).
    """
    with _CUSTOM_FILTER_OPERATORS_LOCK:
        return sorted(ALLOWED_FILTER_OPS)


ALLOWED_JOIN_TYPES = {
    "left",
    "inner",
    "right",
    "full",
    "left join",
    "inner join",
    "right join",
    "full join",
}


def _check_ident(ident: Any, label: str) -> None:
    if not isinstance(ident, str) or not ident.strip():
        raise ValidationError(f"Field '{label}' must be a non-empty string.")
    if not IDENTIFIER_REGEX.match(ident):
        raise ValidationError(f"Invalid {label} identifier name: '{ident}'")
    parts = ident.split(".")
    if any(len(p) > 128 for p in parts):
        raise ValidationError(
            f"{label} identifier part exceeds maximum allowed length (128): '{ident}'"
        )


def _public_attrs(obj: Any) -> dict[str, Any]:
    """Public (non-underscore) attributes of a dataclass / Pydantic-like object."""
    return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}


def _as_item_dict(item: Any, kind: str) -> dict[str, Any]:
    """Normalise a spec list item (dict or attribute object) to a plain dict."""
    if hasattr(item, "__dict__"):
        return _public_attrs(item)
    if isinstance(item, dict):
        return item
    raise ValidationError(f"Invalid {kind} item type: {type(item).__name__}")


def _check_unknown_keys(
    item: dict[str, Any], allowed: set[str], label: str, allow_unknown_keys: bool
) -> None:
    if allow_unknown_keys:
        return
    unknown = set(item.keys()) - allowed
    if unknown:
        raise ValidationError(
            f"Unexpected field(s) in {label} specification: {', '.join(sorted(unknown))}"
        )


# spec key -> (human label in the "too many" error, maximum item count)
_LIST_SECTION_LIMITS: dict[str, tuple[str, int]] = {
    "columns": ("column projections", MAX_PROJECTIONS),
    "joins": ("joins", MAX_JOINS),
    "filters": ("filters", MAX_FILTERS),
    "having": ("having specifications", MAX_HAVING),
    "order_by": ("order by specifications", MAX_ORDER_BY),
}


def _list_section(spec: dict[str, Any], key: str) -> list[Any] | tuple[Any, ...]:
    """Return the (type- and size-checked) list at ``spec[key]``; empty when unset."""
    items = spec.get(key, [])
    if items is not None and not isinstance(items, (list, tuple)):
        raise ValidationError(f"Field '{key}' must be a list.")
    label, maximum = _LIST_SECTION_LIMITS[key]
    if items and len(items) > maximum:
        raise ValidationError(
            f"Too many {label}: {len(items)} exceeds maximum of {maximum}."
        )
    return items or []


def _check_column_name(name: str) -> None:
    if name == "*":
        return
    if name.endswith(".*"):
        _check_ident(name[:-2], "column table prefix")
    else:
        _check_ident(name, "column")


def _validate_case_when(case_when: Any) -> None:
    if hasattr(case_when, "__dict__"):
        cw_dict = _public_attrs(case_when)
    elif isinstance(case_when, dict):
        cw_dict = case_when
    else:
        raise ValidationError("Field 'case_when' must be a dictionary or CaseWhenSpec.")
    branches = cw_dict.get("branches", [])
    if not isinstance(branches, (list, tuple)) or len(branches) == 0:
        raise ValidationError(
            "'case_when' must contain a non-empty list of 'branches'."
        )
    for b in branches:
        if hasattr(b, "__dict__"):
            b_dict = _public_attrs(b)
        elif isinstance(b, dict):
            b_dict = b
        else:
            raise ValidationError(
                "Each branch in 'case_when' must be a dict or CaseWhenBranch."
            )
        if not b_dict.get("condition"):
            raise ValidationError("Each branch in 'case_when' must have a 'condition'.")


def _validate_column_dict(col: dict[str, Any]) -> None:
    raw_col = col.get("column", col.get("name"))
    case_when = col.get("case_when")
    if case_when is not None:
        _validate_case_when(case_when)

    if raw_col is None:
        if (
            case_when is None
            and col.get("expression") is None
            and col.get("raw_expression") is None
        ):
            return
    elif isinstance(raw_col, str):
        _check_column_name(raw_col)
    else:
        raise ValidationError("Column name must be a string.")

    agg = col.get("agg") or col.get("aggregate")
    if agg is not None and str(agg).lower() not in AGGREGATE_MAP:
        raise ValidationError(f"Unsupported aggregate function: '{agg}'")
    alias = col.get("alias")
    if alias is not None:
        if not isinstance(alias, str):
            raise ValidationError("Column 'alias' must be a string.")
        if len(alias) > 256 or "\x00" in alias:
            raise ValidationError(f"Invalid column alias: '{alias}'")
    tbl = col.get("table")
    if tbl is not None:
        _check_ident(tbl, "column table")

    time_grain = col.get("time_grain") or col.get("timeGrain") or col.get("grain")
    if time_grain is not None:
        from query_builder.semantic import SUPPORTED_TIME_GRAINS

        if str(time_grain).lower() not in SUPPORTED_TIME_GRAINS:
            raise ValidationError(f"Unsupported time grain: '{time_grain}'")


def _validate_columns(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    for col in _list_section(spec, "columns"):
        if isinstance(col, str):
            _check_column_name(col)
        elif isinstance(col, dict):
            _check_unknown_keys(col, ALLOWED_COLUMN_KEYS, "column", allow_unknown_keys)
            _validate_column_dict(col)
        else:
            raise ValidationError(
                f"Invalid column specification item type: {type(col).__name__}"
            )

    metrics = spec.get("metrics")
    if metrics is not None and not isinstance(metrics, (list, tuple)):
        raise ValidationError("Field 'metrics' must be a list.")


# optional join identifier fields -> label used in the error message
_JOIN_IDENT_FIELDS = (
    ("alias", "join alias"),
    ("left_table", "join left_table"),
    ("left_col", "join left_col"),
    ("right_col", "join right_col"),
)


def _validate_join(raw: Any, allow_unknown_keys: bool) -> None:
    j_dict = _as_item_dict(raw, "join")
    _check_unknown_keys(j_dict, ALLOWED_JOIN_KEYS, "join", allow_unknown_keys)
    j_tbl = j_dict.get("table")
    if j_tbl is None:
        raise ValidationError("Missing join target 'table'.")
    _check_ident(j_tbl, "join table")
    for field, label in _JOIN_IDENT_FIELDS:
        if j_dict.get(field):
            _check_ident(j_dict[field], label)
    if "on" in j_dict and j_dict["on"] is not None:
        on_val = j_dict["on"]
        if not isinstance(on_val, (list, tuple)):
            raise ValidationError("Join 'on' condition must be a list.")
        if len(on_val) > 10:
            raise ValidationError("Too many join ON conditions (maximum 10).")
        for cond in on_val:
            c_dict = cond.__dict__ if hasattr(cond, "__dict__") else cond
            if (
                not isinstance(c_dict, dict)
                or "left" not in c_dict
                or "right" not in c_dict
            ):
                raise ValidationError(
                    "Join ON condition must contain 'left' and 'right'."
                )
            _check_ident(c_dict["left"], "join on left")
            _check_ident(c_dict["right"], "join on right")


def _validate_joins(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    for j in _list_section(spec, "joins"):
        _validate_join(j, allow_unknown_keys)


def _validate_filter(
    raw: Any,
    allow_unknown_keys: bool,
    extra_ops: set[str] | None = None,
) -> None:
    flt_dict = _as_item_dict(raw, "filter")
    _check_unknown_keys(flt_dict, ALLOWED_FILTER_KEYS, "filter", allow_unknown_keys)

    op = str(flt_dict.get("op", flt_dict.get("operator", "eq"))).strip().lower()
    valid_ops = (
        ALLOWED_FILTER_OPS if extra_ops is None else (ALLOWED_FILTER_OPS | extra_ops)
    )
    if op not in valid_ops:
        raise ValidationError(f"Unsupported filter operator: '{op}'")

    val = flt_dict.get("value")
    subquery = flt_dict.get("subquery")
    if (
        subquery is not None
        or (isinstance(val, dict) and "table" in val)
        or (hasattr(val, "__dict__") and hasattr(val, "table"))
    ):
        sub_spec = subquery if subquery is not None else val
        sub_dict = sub_spec if isinstance(sub_spec, dict) else sub_spec.__dict__
        validate_query_spec(
            sub_dict,
            allow_unknown_keys=allow_unknown_keys,
            extra_filter_ops=extra_ops,
        )
        flt_col = flt_dict.get("column")
        if flt_col is not None:
            _check_ident(flt_col, "filter column")
    elif op in ("exists", "not_exists", "not exists"):
        raise ValidationError("EXISTS filter requires a nested subquery.")
    else:
        flt_col = flt_dict.get("column")
        if flt_col is None:
            return
        _check_ident(flt_col, "filter column")

    prefix = (
        flt_dict.get("tablePrefix")
        or flt_dict.get("table_prefix")
        or flt_dict.get("table")
    )
    if prefix is not None:
        _check_ident(prefix, "filter table prefix")

    if op in ("in", "not in", "not_in"):
        if isinstance(val, (list, tuple, set)) and len(val) > MAX_IN_VALUES:
            raise ValidationError(
                f"IN filter value count ({len(val)}) exceeds maximum limit of {MAX_IN_VALUES}."
            )
        elif isinstance(val, str):
            items = [v for v in val.split(",") if v.strip()]
            if len(items) > MAX_IN_VALUES:
                raise ValidationError(
                    f"IN filter value count ({len(items)}) exceeds maximum limit of {MAX_IN_VALUES}."
                )
    elif op in ("between", "not_between", "not between") and (
        (isinstance(val, (list, tuple)) and len(val) != 2)
        or (isinstance(val, str) and (" AND " not in val and "," not in val))
    ):
        raise ValidationError("BETWEEN filter requires exactly 2 bounds.")


def _validate_filters(
    spec: dict[str, Any],
    allow_unknown_keys: bool,
    extra_ops: set[str] | None = None,
) -> None:
    for flt in _list_section(spec, "filters"):
        _validate_filter(flt, allow_unknown_keys, extra_ops=extra_ops)

    if (
        "filter_join" in spec
        and spec["filter_join"] is not None
        and not isinstance(spec["filter_join"], str)
    ):
        raise ValidationError("Field 'filter_join' must be a string.")


def _validate_having_item(raw: Any, allow_unknown_keys: bool) -> None:
    h_dict = _as_item_dict(raw, "having")
    _check_unknown_keys(h_dict, ALLOWED_HAVING_KEYS, "having", allow_unknown_keys)
    h_col = h_dict.get("column")
    if h_col is None:
        return
    if h_col != "*":
        _check_ident(h_col, "having column")
    h_agg = str(h_dict.get("agg", h_dict.get("aggregate", "count"))).lower()
    if h_agg not in AGGREGATE_MAP:
        raise ValidationError(f"Unsupported having aggregate: '{h_agg}'")
    h_op = str(h_dict.get("op", h_dict.get("operator", "gt"))).lower()
    if h_op not in OPERATOR_MAP:
        raise ValidationError(f"Unsupported having operator: '{h_op}'")
    h_pfx = (
        h_dict.get("tablePrefix") or h_dict.get("table_prefix") or h_dict.get("table")
    )
    if h_pfx is not None:
        _check_ident(h_pfx, "having table prefix")


def _validate_having(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    for h in _list_section(spec, "having"):
        _validate_having_item(h, allow_unknown_keys)


def _validate_order_by_item(raw: Any, allow_unknown_keys: bool) -> None:
    o_dict = _as_item_dict(raw, "order_by")
    _check_unknown_keys(o_dict, ALLOWED_ORDER_BY_KEYS, "order by", allow_unknown_keys)
    o_col = o_dict.get("column")
    if o_col is None:
        return
    _check_ident(o_col, "order_by column")
    o_pfx = (
        o_dict.get("tablePrefix") or o_dict.get("table_prefix") or o_dict.get("table")
    )
    if o_pfx is not None:
        _check_ident(o_pfx, "order_by table prefix")
    o_nulls = o_dict.get("nulls")
    if o_nulls is not None and str(o_nulls).strip().upper() not in {
        "FIRST",
        "LAST",
        "NULLS FIRST",
        "NULLS LAST",
    }:
        raise ValidationError(
            f"Invalid order_by 'nulls': '{o_nulls}'. Must be 'FIRST' or 'LAST'."
        )


def _validate_order_by(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    for o in _list_section(spec, "order_by"):
        _validate_order_by_item(o, allow_unknown_keys)


def _check_bounded_int(
    spec: dict[str, Any], key: str, label: str, maximum: int
) -> None:
    """``spec[key]``, when set, must be an int in ``0..maximum``."""
    if key not in spec or spec[key] is None:
        return
    try:
        number = int(spec[key])
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid {key} value: {spec[key]}") from e
    if number < 0:
        raise ValidationError(f"{label} must be non-negative.")
    if number > maximum:
        raise ValidationError(
            f"{label} ({number}) exceeds maximum allowed limit of {maximum}."
        )


def _validate_pagination(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    _check_bounded_int(spec, "limit", "Limit", MAX_LIMIT)
    _check_bounded_int(spec, "offset", "Offset", MAX_OFFSET)
    if (
        "distinct" in spec
        and spec["distinct"] is not None
        and not isinstance(spec["distinct"], bool)
    ):
        raise ValidationError("Field 'distinct' must be a boolean.")


_VALID_VECTOR_METRICS = {"cosine", "euclidean", "l2", "dot_product", "inner_product"}


def _check_vector_values(vec: Any, label: str) -> None:
    if not isinstance(vec, (list, tuple)) or len(vec) == 0:
        raise ValidationError(
            f"Field '{label}.vector' must be a non-empty list of numbers."
        )
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in vec):
        raise ValidationError(f"All elements in '{label}.vector' must be numbers.")


def _check_top_k(top_k: Any, label: str) -> None:
    if not isinstance(top_k, int) or top_k <= 0 or top_k > MAX_LIMIT:
        raise ValidationError(
            f"Field '{label}.top_k' must be an integer between 1 and {MAX_LIMIT}."
        )


def _check_vector_metric(metric: Any, label: str) -> None:
    if str(metric).lower() not in _VALID_VECTOR_METRICS:
        raise ValidationError(
            f"Invalid {label} 'metric': '{metric}'. Must be one of {sorted(_VALID_VECTOR_METRICS)}."
        )


_VECTOR_SEARCH_KEYS = {
    "vector",
    "column",
    "top_k",
    "metric",
    "include_distances",
    "min_score",
}


def _validate_vector_search(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    vs = spec.get("vector_search")
    if vs is None:
        return
    if isinstance(vs, dict):
        _check_unknown_keys(
            vs, _VECTOR_SEARCH_KEYS, "vector_search", allow_unknown_keys
        )
        vec = vs.get("vector")
        col = vs.get("column", "embedding")
        top_k = vs.get("top_k", 10)
        metric = vs.get("metric", "cosine")
        min_score = vs.get("min_score")
    elif hasattr(vs, "vector"):
        vec = vs.vector
        col = getattr(vs, "column", "embedding")
        top_k = getattr(vs, "top_k", 10)
        metric = getattr(vs, "metric", "cosine")
        min_score = getattr(vs, "min_score", None)
    else:
        raise ValidationError(
            "Field 'vector_search' must be a dictionary or VectorSearchSpec."
        )

    _check_vector_values(vec, "vector_search")
    _check_ident(col, "vector_search column")
    _check_top_k(top_k, "vector_search")
    _check_vector_metric(metric, "vector_search")
    if min_score is not None and not isinstance(min_score, (int, float)):
        raise ValidationError(
            "Field 'vector_search.min_score' must be a number or None."
        )


_HYBRID_SEARCH_KEYS = {
    "vector",
    "vector_column",
    "query_text",
    "text_columns",
    "alpha",
    "fusion",
    "rrf_k",
    "top_k",
    "metric",
    "include_scores",
}
_HYBRID_DEFAULTS: dict[str, Any] = {
    "vector": None,
    "vector_column": "embedding",
    "query_text": "",
    "text_columns": [],
    "alpha": 0.5,
    "fusion": "rrf",
    "rrf_k": 60,
    "top_k": 10,
    "metric": "cosine",
}


def _validate_hybrid_search(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    hs = spec.get("hybrid_search")
    if hs is None:
        return
    if isinstance(hs, dict):
        _check_unknown_keys(
            hs, _HYBRID_SEARCH_KEYS, "hybrid_search", allow_unknown_keys
        )
        fields = {k: hs.get(k, d) for k, d in _HYBRID_DEFAULTS.items()}
    elif hasattr(hs, "vector"):
        fields = {k: getattr(hs, k, d) for k, d in _HYBRID_DEFAULTS.items()}
        fields["vector"] = hs.vector
    else:
        raise ValidationError(
            "Field 'hybrid_search' must be a dictionary or HybridSearchSpec."
        )

    _check_vector_values(fields["vector"], "hybrid_search")
    _check_ident(fields["vector_column"], "hybrid_search vector_column")

    if not isinstance(fields["query_text"], str):
        raise ValidationError("Field 'hybrid_search.query_text' must be a string.")

    t_cols = fields["text_columns"]
    if not isinstance(t_cols, (list, tuple)):
        raise ValidationError(
            "Field 'hybrid_search.text_columns' must be a list of column names."
        )
    for tc in t_cols:
        _check_ident(tc, "hybrid_search text_column")

    alpha = fields["alpha"]
    if not isinstance(alpha, (int, float)) or not (0.0 <= float(alpha) <= 1.0):
        raise ValidationError(
            "Field 'hybrid_search.alpha' must be a number between 0.0 and 1.0."
        )

    valid_fusions = {"rrf", "linear"}
    if str(fields["fusion"]).lower() not in valid_fusions:
        raise ValidationError(
            f"Invalid hybrid_search 'fusion': '{fields['fusion']}'. Must be one of {sorted(valid_fusions)}."
        )

    rrf_k = fields["rrf_k"]
    if not isinstance(rrf_k, int) or rrf_k <= 0:
        raise ValidationError("Field 'hybrid_search.rrf_k' must be a positive integer.")

    _check_top_k(fields["top_k"], "hybrid_search")
    _check_vector_metric(fields["metric"], "hybrid_search")


def _validate_ctes(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    ctes_val = spec.get("ctes")
    if ctes_val is None:
        return
    if not isinstance(ctes_val, (list, tuple)):
        raise ValidationError("Field 'ctes' must be a list.")
    from query_builder.ast_validator import validate_cte_dag

    cte_res = validate_cte_dag(list(ctes_val))
    if not cte_res.get("valid", True):
        raise ValidationError(cte_res["violations"][0])


def _validate_window_functions(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    wf_val = spec.get("window_functions")
    if wf_val is None:
        return
    if not isinstance(wf_val, (list, tuple)):
        raise ValidationError("Field 'window_functions' must be a list.")
    from query_builder.ast_validator import validate_window_function_spec

    for wf in wf_val:
        wf_res = validate_window_function_spec(wf)
        if not wf_res.get("valid", True):
            raise ValidationError(wf_res["violations"][0])


_VALID_SET_OPS = {"UNION", "UNION ALL", "INTERSECT", "EXCEPT", "MINUS"}


def _validate_set_operations(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    so_val = spec.get("set_operations")
    if so_val is None:
        return
    if not isinstance(so_val, (list, tuple)):
        raise ValidationError("Field 'set_operations' must be a list.")
    for so in so_val:
        if hasattr(so, "__dict__"):
            so_dict = _public_attrs(so)
        elif isinstance(so, dict):
            so_dict = so
        else:
            raise ValidationError(
                "Each set operation must be a dict or SetOperationSpec."
            )
        op = str(so_dict.get("operation", "UNION")).upper().strip()
        if op not in _VALID_SET_OPS:
            raise ValidationError(
                f"Invalid set operation: '{op}'. Must be one of {sorted(_VALID_SET_OPS)}."
            )
        q = so_dict.get("query")
        if not q:
            raise ValidationError(
                "Set operation must include a 'query' sub-specification."
            )
        if isinstance(q, dict):
            validate_query_spec(q, allow_unknown_keys=allow_unknown_keys)
        elif hasattr(q, "__dict__"):
            validate_query_spec(q.__dict__, allow_unknown_keys=allow_unknown_keys)


def _validate_grouping_type(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    if spec.get("grouping_type") is None:
        return
    gt = str(spec["grouping_type"]).lower().strip()
    if gt not in {"standard", "rollup", "cube", "grouping_sets"}:
        raise ValidationError(
            f"Invalid 'grouping_type': '{gt}'. Must be one of 'standard', 'rollup', 'cube', 'grouping_sets'."
        )


def _is_listlike(value: Any) -> bool:
    return isinstance(value, (list, tuple))


# (spec key, predicate accepting the value, error message), checked in order
_SHAPE_RULES: tuple[tuple[str, Callable[[Any], bool], str], ...] = (
    (
        "grouping_sets",
        lambda v: _is_listlike(v) or hasattr(v, "sets"),
        "Field 'grouping_sets' must be a list of column lists.",
    ),
    (
        "rollup",
        lambda v: isinstance(v, (dict, list, tuple)) or hasattr(v, "columns"),
        "Field 'rollup' must be a RollupSpec or dict.",
    ),
    (
        "cube",
        lambda v: isinstance(v, (dict, list, tuple)) or hasattr(v, "columns"),
        "Field 'cube' must be a CubeSpec or dict.",
    ),
    (
        "pivot",
        lambda v: isinstance(v, dict) or hasattr(v, "column"),
        "Field 'pivot' must be a PivotSpec or dict.",
    ),
)


def _validate_shapes(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    for key, accepts, message in _SHAPE_RULES:
        value = spec.get(key)
        if value is not None and not accepts(value):
            raise ValidationError(message)


def _validate_unknown_spec_keys(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    if not allow_unknown_keys:
        unknown = set(spec.keys()) - ALLOWED_SPEC_KEYS
        if unknown:
            raise ValidationError(
                f"Unexpected field(s) in query specification: {', '.join(sorted(unknown))}"
            )


def _validate_table(spec: dict[str, Any], allow_unknown_keys: bool) -> None:
    table = spec.get("table")
    if table is None:
        raise ValidationError(
            "Missing required 'table' parameter in query specification."
        )
    if isinstance(table, dict) or hasattr(table, "__dict__"):
        sub_dict = table if isinstance(table, dict) else table.__dict__
        if "subquery" in sub_dict and "table" not in sub_dict:
            inner_sub = sub_dict["subquery"]
            inner_dict: Any = (
                inner_sub
                if isinstance(inner_sub, dict)
                else getattr(inner_sub, "__dict__", None)
            )
            if not isinstance(inner_dict, dict):
                raise ValidationError(
                    "Derived table 'subquery' must be a QuerySpec or dictionary."
                )
            if sub_dict.get("alias") is not None:
                _check_ident(sub_dict["alias"], "subquery alias")
            validate_query_spec(inner_dict, allow_unknown_keys=allow_unknown_keys)
        else:
            validate_query_spec(sub_dict, allow_unknown_keys=allow_unknown_keys)
    else:
        _check_ident(table, "table")


# Validation steps, run in order; the first violation raised wins.
_VALIDATION_STEPS: tuple[Callable[[dict[str, Any], bool], None], ...] = (
    _validate_unknown_spec_keys,
    _validate_table,
    _validate_columns,
    _validate_joins,
    _validate_filters,
    _validate_having,
    _validate_order_by,
    _validate_pagination,
    _validate_vector_search,
    _validate_hybrid_search,
    _validate_ctes,
    _validate_window_functions,
    _validate_set_operations,
    _validate_grouping_type,
    _validate_shapes,
)


def validate_query_spec(
    spec: dict[str, Any],
    allow_unknown_keys: bool = False,
    extra_filter_ops: set[str] | None = None,
) -> None:
    """
    Validates an untrusted query specification dictionary against schema rules,
    acceptable keys, data types, and defensive DoS limits.
    """
    if not isinstance(spec, dict):
        raise ValidationError(
            f"Query spec must be a dictionary, got {type(spec).__name__}"
        )
    for step in _VALIDATION_STEPS:
        if step is _validate_filters:
            _validate_filters(spec, allow_unknown_keys, extra_ops=extra_filter_ops)
        else:
            step(spec, allow_unknown_keys)


_EXISTS_OPS = ("exists", "not_exists", "not exists")

# filter operator -> (substring_param kind, negated)
_SUBSTRING_OPS: dict[str, tuple[str, bool]] = {
    "contains": ("contains", False),
    "not_contains": ("contains", True),
    "not contains": ("contains", True),
    "starts_with": ("starts", False),
    "startswith": ("starts", False),
    "not_starts_with": ("starts", True),
    "not startswith": ("starts", True),
    "ends_with": ("ends", False),
    "endswith": ("ends", False),
    "not_ends_with": ("ends", True),
    "not endswith": ("ends", True),
}


class QueryCompiler:
    """
    Translates a declarative JSON QueryBuilderSpec into safe, parameterized SQL.
    Supports dialect switching, automatic join resolution, tenant/user isolation,
    and automatic COUNT subquery construction.
    """

    def _sql_op(self, op: str) -> str:
        """Comparison operator text; dialects may spell not-equal ``<>`` (``neq_operator``)."""
        text = OPERATOR_MAP[op]
        if text == "!=":
            return getattr(self.dialect, "neq_operator", "!=")
        return text

    def __init__(
        self,
        spec: dict[str, Any] | Any,
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        force_user_filter: bool = False,
        tenant_id: Any = None,
        dialect: str | BaseDialect | None = None,
        ownership_paths: dict[str, list[list[tuple[str, str, str]]]] | None = None,
        max_limit: int = 100,
        validate_spec: bool = True,
        allow_unknown_keys: bool = False,
        middleware: Any = None,
        semantic_models: Any = None,
        capabilities: Any = None,
        inner: bool = False,
        param_counter: list[int] | None = None,
        custom_operators: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        # Nested queries (CTE bodies, subqueries in FROM / IN / EXISTS) must not
        # get the implicit page LIMIT: it would silently truncate the inner
        # result set (and MySQL rejects LIMIT inside IN subqueries).
        self.inner = inner
        self._param_counter: list[int] = (
            param_counter if param_counter is not None else [0]
        )
        self.custom_operators: dict[str, Callable[..., Any]] | None = (
            {k.lower().strip(): v for k, v in custom_operators.items()}
            if custom_operators is not None
            else None
        )
        if capabilities is not None:
            from query_builder.capabilities import EngineCapabilities

            if isinstance(capabilities, EngineCapabilities):
                self.capabilities: EngineCapabilities | None = capabilities
            elif isinstance(capabilities, dict):
                self.capabilities = EngineCapabilities.from_dict(capabilities)
            else:
                self.capabilities = None
        else:
            self.capabilities = None

        if middleware is not None:
            from query_builder.middleware import MiddlewarePipeline

            self.middleware: MiddlewarePipeline | None = MiddlewarePipeline.ensure(
                middleware
            )
        else:
            self.middleware = None
        if hasattr(spec, "__dict__"):
            # Dataclass or Pydantic model
            self.spec = {
                k: v for k, v in spec.__dict__.items() if not k.startswith("_")
            }
        elif isinstance(spec, dict):
            self.spec = spec
        else:
            raise CompilationError(f"Unsupported spec type: {type(spec)}")

        if validate_spec:
            extra_ops = (
                set(self.custom_operators.keys()) if self.custom_operators else None
            )
            validate_query_spec(
                self.spec,
                allow_unknown_keys=allow_unknown_keys,
                extra_filter_ops=extra_ops,
            )

        if self.capabilities:
            self._validate_capabilities()

        self.user_id = user_id
        self.force_user_filter = force_user_filter
        self.tenant_id = (
            tenant_id if tenant_id is not None else self.spec.get("tenant_id")
        )
        self.dialect = (
            dialect if isinstance(dialect, BaseDialect) else get_dialect(dialect)
        )
        self.ownership_paths = ownership_paths or {}
        self.max_limit = max_limit

        self.schema = schema or {}
        if isinstance(self.schema, SchemaSnapshot) or hasattr(self.schema, "tables"):
            self.tables_meta: dict[str, Any] = getattr(self.schema, "tables", {})
            self.rel_meta: list[dict[str, Any]] = getattr(
                self.schema, "relationships", []
            )
            self.foreign_keys: list[dict[str, Any]] = getattr(
                self.schema, "foreign_keys", []
            )
        elif isinstance(self.schema, dict):
            self.tables_meta = self.schema.get("tables", {})
            self.rel_meta = self.schema.get("relationships", [])
            self.foreign_keys = self.schema.get("foreign_keys", [])
        else:
            self.tables_meta = {}
            self.rel_meta = []
            self.foreign_keys = []

        self.tables_meta = dict(self.tables_meta)
        ctes = self.spec.get("ctes") or []
        for cte in ctes:
            c_name = getattr(cte, "name", None) or (
                cte.get("name") if isinstance(cte, dict) else None
            )
            if c_name and c_name not in self.tables_meta:
                self.tables_meta[c_name] = {"name": c_name, "columns": []}

        self.semantic_models: dict[str, Any] = {}
        if semantic_models:
            from query_builder.semantic import SemanticModel

            if isinstance(semantic_models, list):
                for sm in semantic_models:
                    if isinstance(sm, SemanticModel):
                        self.semantic_models[sm.name] = sm
                        self.semantic_models[sm.table_name] = sm
                    elif isinstance(sm, dict):
                        m = SemanticModel.from_dict(sm)
                        self.semantic_models[m.name] = m
                        self.semantic_models[m.table_name] = m
            elif isinstance(semantic_models, dict):
                for k, v in semantic_models.items():
                    if isinstance(v, SemanticModel):
                        self.semantic_models[k] = v
                    elif isinstance(v, dict):
                        self.semantic_models[k] = SemanticModel.from_dict(v)

        spec_sm = self.spec.get("semantic_model") or self.spec.get("semantic_models")
        if spec_sm:
            from query_builder.semantic import (
                SemanticModel,
                load_semantic_models_from_dict,
            )

            if isinstance(spec_sm, dict):
                for m in load_semantic_models_from_dict(spec_sm):
                    self.semantic_models[m.name] = m
                    self.semantic_models[m.table_name] = m
            elif isinstance(spec_sm, list):
                for sm in spec_sm:
                    if isinstance(sm, dict):
                        m = SemanticModel.from_dict(sm)
                        self.semantic_models[m.name] = m
                        self.semantic_models[m.table_name] = m

        self.table_aliases: dict[str, str] = {}
        self._alias_counter = 0
        self.params: list[Any] = []
        # params that belong to the SELECT list / ORDER BY only (vector distance); the COUNT
        # query has neither, so they must not be passed with it
        self._count_skip_lead = 0
        self.where_clauses: list[str] = []
        self.having_clauses: list[str] = []
        self.select_clause_items: list[str] = []
        self.select_column_names: list[str] = []
        self.group_by_items: list[str] = []
        self.order_by_items: list[str] = []
        self.join_clauses: list[str] = []

        self.has_aggregation = False
        #: Output labels of SELECT items that are not grouping columns (aggregates), which ORDER BY may name directly.
        self._aggregate_labels: set[str] = set()
        #: Aliases the spec gives its selected columns (``{"column": ..., "alias": ...}``), which an unprefixed ORDER BY
        #: may name when they are not a column of the base table.
        self._declared_aliases: set[str] = set()
        #: True while ``compile_search`` builds the whole result, to be filtered and then paged by the wrapper.
        self._unpaged = False
        self._ownership_alias_counter = AliasCounter()

        # Per-compile state shared between the clause steps of ``compile``.
        self._base_table: Any = None
        self._clean_base = ""
        self._base_alias = ""
        self._from_str = ""
        self._from_params: list[Any] = []
        self._group_by_params: list[Any] = []
        self._joined_targets: list[tuple[str, str]] = []
        self._is_subquery_from = False
        self._count_params_end = 0
        self.has_vector_search = False
        self.vector_distance_expr: str | None = None
        self._vector_include_dist = True
        self._vector_param_val: Any = None
        self._vector_min_score: float | None = None
        self.has_hybrid_search = False
        self.hybrid_score_expr: str | None = None
        self._hybrid_include_scores = True
        self._hybrid_vector_param: Any = None
        self._hybrid_text_param: Any = None
        self._hybrid_text_quoted_refs: list[str] = []

    def _validate_capabilities(self) -> None:
        """Validates that all query features used in self.spec are enabled in self.capabilities."""
        if not self.capabilities:
            return
        if self.spec.get("ctes"):
            self.capabilities.require_feature("ctes")
        if self.spec.get("window_functions"):
            self.capabilities.require_feature("window_functions")
        if (
            self.spec.get("rollup")
            or self.spec.get("cube")
            or self.spec.get("grouping_sets")
            or self.spec.get("pivot")
            or self.spec.get("grouping_type")
        ):
            self.capabilities.require_feature("analytical_grouping")
        if self.spec.get("vector_search") or self.spec.get("hybrid_search"):
            self.capabilities.require_feature("vector_search")
        if self.spec.get("joins"):
            self.capabilities.require_feature("joins")
        if self.spec.get("order_by"):
            self.capabilities.require_feature("sorts")
        if self.spec.get("filters") or self.spec.get("having"):
            self.capabilities.require_feature("filters")
        if self.spec.get("distinct") is True or "limit" in self.spec:
            self.capabilities.require_feature("distinct_limit")
        cols = self.spec.get("columns", [])
        for c in cols:
            if isinstance(c, dict):
                if c.get("case_when"):
                    self.capabilities.require_feature("calculated_fields")
                if c.get("expression") or c.get("raw_expression"):
                    if not (c.get("metric") or c.get("dimension")):
                        self.capabilities.require_feature("custom_expressions")
                        self.capabilities.require_feature("calculated_fields")
            elif (
                hasattr(c, "expression")
                or hasattr(c, "case_when")
                or hasattr(c, "raw_expression")
            ):
                if getattr(c, "case_when", None):
                    self.capabilities.require_feature("calculated_fields")
                if getattr(c, "expression", None) or getattr(c, "raw_expression", None):
                    if not (
                        getattr(c, "metric", None) or getattr(c, "dimension", None)
                    ):
                        self.capabilities.require_feature("custom_expressions")
                        self.capabilities.require_feature("calculated_fields")

    def _aggregate_template(self, agg: str) -> str:
        if agg in ("avg", "count_distinct"):
            return getattr(self.dialect, f"{agg}_template", AGGREGATE_MAP[agg])
        return AGGREGATE_MAP[agg]

    def _unpaginated_nested(self) -> bool:
        """True for a CTE/subquery body that asked for no LIMIT/OFFSET."""
        return bool(
            self.inner
            and "limit" not in self.spec
            and not self.spec.get("offset")
            and not (self.has_vector_search or self.has_hybrid_search)
        )

    def _generate_unique_alias(self) -> str:
        self._alias_counter += 1
        alias = f"t{self._alias_counter}"
        while alias in self.table_aliases.values():
            self._alias_counter += 1
            alias = f"t{self._alias_counter}"
        return alias

    def _get_alias(
        self,
        table_name: str,
        explicit_alias: str | None = None,
        default_alias: str | None = None,
    ) -> str:
        """Returns or creates a stable short alias (e.g. t1, t2) for a given table."""
        if explicit_alias:
            _check_ident(explicit_alias, "table alias")
            self.table_aliases[explicit_alias] = explicit_alias
            self.table_aliases[table_name] = explicit_alias
            clean = table_name.split(".")[-1]
            self.table_aliases[clean] = explicit_alias
            return explicit_alias

        if not isinstance(table_name, str) or not table_name.strip():
            raise CompilationError(f"Invalid table name: '{table_name}'")
        if not IDENTIFIER_REGEX.match(table_name):
            raise CompilationError(f"Invalid table identifier name: '{table_name}'")

        clean = table_name.split(".")[-1]
        if table_name in self.table_aliases:
            return self.table_aliases[table_name]
        if clean in self.table_aliases:
            return self.table_aliases[clean]

        if default_alias and default_alias not in self.table_aliases.values():
            alias = default_alias
            try:
                num_part = int(default_alias.lstrip("t"))
                self._alias_counter = max(self._alias_counter, num_part)
            except ValueError:
                pass
        else:
            alias = self._generate_unique_alias()

        self.table_aliases[table_name] = alias
        self.table_aliases[clean] = alias
        self.table_aliases[alias] = alias
        return alias

    def _resolve_column_ref(
        self, col_ref: str | None, default_table: str, target_alias: str | None = None
    ) -> tuple[str, str, str]:
        """Resolves a column reference to (alias, col_name, quoted_column_ref)."""
        if not isinstance(col_ref, str) or not col_ref.strip():
            raise CompilationError(f"Invalid column reference: '{col_ref}'")
        dotted = self.dialect.dotted_column_names
        if "." in col_ref and not dotted:
            parts = col_ref.rsplit(".", 1)
            tbl = parts[0]
            col = parts[1]
        else:
            tbl = default_table
            col = col_ref

        clean_col = col if dotted else col.split(".")[-1]
        if clean_col != "*" and not IDENTIFIER_REGEX.match(clean_col):
            raise CompilationError(f"Invalid column identifier name: '{col}'")

        if not IDENTIFIER_REGEX.match(tbl):
            raise CompilationError(f"Invalid table identifier name: '{tbl}'")

        clean_tbl = tbl.split(".")[-1]
        clean_default = default_table.split(".")[-1]

        if target_alias and (
            tbl == target_alias
            or clean_tbl == target_alias
            or tbl == default_table
            or clean_tbl == clean_default
        ):
            alias = target_alias
        elif tbl in self.table_aliases:
            alias = self.table_aliases[tbl]
        elif clean_tbl in self.table_aliases:
            alias = self.table_aliases[clean_tbl]
        else:
            alias = self._get_alias(clean_tbl)

        if not self.dialect.supports_table_aliases:
            quoted_ref = (
                "*" if clean_col == "*" else self.dialect.quote_identifier(clean_col)
            )
        elif clean_col == "*":
            quoted_ref = f"{self.dialect.quote_identifier(alias)}.*"
        else:
            quoted_ref = f"{self.dialect.quote_identifier(alias)}.{self.dialect.quote_identifier(clean_col)}"
        return alias, clean_col, quoted_ref

    def _compile_case_when(
        self,
        cw_spec: dict[str, Any] | Any,
        clean_base_table: str,
    ) -> str:
        """Compiles declarative CASE WHEN branches into SQL conditional expression."""
        if hasattr(cw_spec, "__dict__"):
            cw_dict = {
                k: v for k, v in cw_spec.__dict__.items() if not k.startswith("_")
            }
        elif isinstance(cw_spec, dict):
            cw_dict = cw_spec
        else:
            raise CompilationError("Invalid case_when specification type.")

        branches = cw_dict.get("branches", [])
        when_tokens: list[str] = []
        for b in branches:
            if hasattr(b, "__dict__"):
                b_dict = {k: v for k, v in b.__dict__.items() if not k.startswith("_")}
            elif isinstance(b, dict):
                b_dict = b
            else:
                continue
            cond = b_dict.get("condition")
            if hasattr(cond, "__dict__"):
                cond = {k: v for k, v in cond.__dict__.items() if not k.startswith("_")}
            elif not isinstance(cond, dict):
                continue

            col_ref = cond.get("column")
            op = str(cond.get("op", cond.get("operator", "eq"))).strip().lower()
            val = cond.get("value")
            pfx = (
                cond.get("table_prefix")
                or cond.get("tablePrefix")
                or cond.get("table")
                or clean_base_table
            )
            _, _, quoted_cond_ref = self._resolve_column_ref(col_ref, pfx)

            if op in ("is_null", "is null"):
                cond_expr = f"{quoted_cond_ref} IS NULL"
            elif op in ("is_not_null", "is not null"):
                cond_expr = f"{quoted_cond_ref} IS NOT NULL"
            elif op in ("in", "not_in", "not in"):
                neg = "NOT " if "not" in op else ""
                in_vals = val if isinstance(val, (list, tuple, set)) else [val]
                placeholders = ", ".join(self.dialect.placeholder for _ in in_vals)
                cond_expr = f"{quoted_cond_ref} {neg}IN ({placeholders})"
                self.params.extend(in_vals)
            elif op in ("between", "not_between", "not between"):
                neg = "NOT " if "not" in op else ""
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    v1, v2 = val[0], val[1]
                else:
                    v1 = v2 = val
                cond_expr = f"{quoted_cond_ref} {neg}BETWEEN {self.dialect.placeholder} AND {self.dialect.placeholder}"
                self.params.extend([v1, v2])
            elif op in OPERATOR_MAP:
                sql_op = self._sql_op(op)
                cond_expr = f"{quoted_cond_ref} {sql_op} {self.dialect.placeholder}"
                self.params.append(val)
            else:
                cond_expr = f"{quoted_cond_ref} = {self.dialect.placeholder}"
                self.params.append(val)

            then_col = b_dict.get("then_column")
            if then_col:
                _, _, quoted_then = self._resolve_column_ref(then_col, clean_base_table)
                then_expr = quoted_then
            else:
                then_val = b_dict.get("then_value")
                then_expr = self.dialect.placeholder
                self.params.append(then_val)

            when_tokens.append(f"WHEN {cond_expr} THEN {then_expr}")

        else_col = cw_dict.get("else_column")
        if else_col:
            _, _, quoted_else = self._resolve_column_ref(else_col, clean_base_table)
            else_expr = quoted_else
        elif "else_value" in cw_dict and cw_dict.get("else_value") is not None:
            else_expr = self.dialect.placeholder
            self.params.append(cw_dict.get("else_value"))
        else:
            else_expr = "NULL"

        return f"CASE {' '.join(when_tokens)} ELSE {else_expr} END"

    # ------------------------------------------------------------------
    # compile(): orchestration. Each private step below owns one clause and
    # mutates the accumulators initialised in ``__init__`` (params, where /
    # having / select / group / order / join lists) in the order the final
    # parameter list requires.
    # ------------------------------------------------------------------
    def compile(
        self, context: dict[str, Any] | None = None
    ) -> tuple[str, list[Any], str, list[Any]]:
        """
        Compiles the query specification.
        Returns:
            Tuple: (main_sql, main_params, count_sql, count_params)
        """
        ctx = context if context is not None else {}
        if self.middleware is not None:
            self.spec = self.middleware.run_pre_compile(self.spec, ctx)

        self._compile_from()
        self._compile_joins()
        self._compile_projections()
        self._compile_top_level_metrics()
        self._compile_vector_search()
        self._compile_hybrid_search()
        self._compile_window_functions()
        self._compile_base_isolation()
        self._compile_join_isolation()
        self._compile_vector_where()
        self._compile_filters()

        # Assemble SQL parts
        is_distinct = self.spec.get("distinct", False) and not self.has_aggregation
        distinct_prefix = "DISTINCT " if is_distinct else ""
        select_str = f"{distinct_prefix}{', '.join(self.select_clause_items)}"
        joins_str = " ".join(self.join_clauses) if self.join_clauses else ""
        where_str = (
            f"WHERE {' AND '.join(self.where_clauses)}" if self.where_clauses else ""
        )
        group_by_str = self._build_group_by()
        if (
            group_by_str
            and self._group_by_params
            and any(item in group_by_str for item in self.group_by_items)
        ):
            self.params.extend(self._group_by_params)
        self._compile_having()
        having_str = (
            f"HAVING {' AND '.join(self.having_clauses)}" if self.having_clauses else ""
        )

        self._count_params_end = len(self.params)
        self._compile_order_by()
        order_by_str = self._build_order_by_clause()
        limit_offset_str, limit_params = self._build_pagination()

        main_sql, main_params = self._assemble_main_query(
            select_str,
            joins_str,
            where_str,
            group_by_str,
            having_str,
            order_by_str,
            limit_offset_str,
            limit_params,
        )
        count_sql, count_params = self._build_count_query(
            joins_str, where_str, group_by_str, having_str
        )

        cte_prefix, cte_params = self._compile_ctes()
        if cte_prefix:
            main_sql = f"{cte_prefix}{main_sql}"
            count_sql = f"{cte_prefix}{count_sql}"
            if getattr(self.dialect, "cte_params_after_main", False):
                main_params = main_params + cte_params
                count_params = count_params + cte_params
            else:
                main_params = cte_params + main_params
                count_params = cte_params + count_params

        if self.spec.get("set_operations"):
            main_sql, main_params, count_sql, count_params = self._apply_set_operations(
                main_sql, main_params
            )

        if self.middleware is not None:
            compilation: dict[str, Any] = {
                "main_sql": main_sql,
                "main_params": main_params,
                "count_sql": count_sql,
                "count_params": count_params,
            }
            compilation = self.middleware.run_post_compile(compilation, ctx)
            return (
                compilation["main_sql"],
                compilation["main_params"],
                compilation["count_sql"],
                compilation["count_params"],
            )

        return main_sql, main_params, count_sql, count_params

    def compile_runnable(
        self, context: dict[str, Any] | None = None, *, pretty: bool = False
    ) -> str | None:
        """The main query with its values written in as SQL literals, to paste into a SQL window; None if it cannot be.

        The bound form from ``compile`` is what should be executed. This is the copy for people (see ``runnable``):
        None for a dialect whose placeholders are not positional, or if the placeholders and values do not line up.
        With ``pretty=True`` the statement is laid out one clause per line with keywords in capitals
        (``runnable.format_sql``), which never changes what it says.
        """
        from query_builder.runnable import (
            BACKSLASH_ESCAPE_DIALECTS,
            format_sql,
            inline_params,
        )

        sql, params, _, _ = self.compile(context)
        runnable = inline_params(
            sql,
            params,
            placeholder=self.dialect.placeholder,
            backslash_escapes=self.dialect.name in BACKSLASH_ESCAPE_DIALECTS,
        )
        return format_sql(runnable) if pretty else runnable

    def compile_search(
        self, term: str, context: dict[str, Any] | None = None
    ) -> tuple[str, list[Any], str, list[Any]]:
        """Like ``compile``, but keep only the rows where some output column contains ``term`` (case-insensitive).

        The whole result is built without its LIMIT/OFFSET and wrapped, ``SELECT * FROM (<query>) AS qb_rows WHERE
        CAST(col AS TEXT) ILIKE ? ESCAPE '!' OR ...``, and the spec's limit and offset then page the matching rows. So the
        search covers every row of the result, not just one page, and the count query counts the matches. ``term`` is a
        bound parameter with its LIKE wildcards escaped, so ``%`` and ``_`` match themselves. Every column name comes from
        the compiler's own output labels and is quoted.

        Raises CompilationError for an empty or over-long term, a query that selects ``*`` (no named columns to search),
        or a dialect without a text cast.
        """
        text = term.strip()
        if not text:
            raise CompilationError("Search text must not be empty.")
        if len(text) > MAX_SEARCH_TERM:
            raise CompilationError(
                f"Search text must be at most {MAX_SEARCH_TERM} characters."
            )
        cast_type = SEARCH_CAST_TYPES.get(self.dialect.name)
        if cast_type is None:
            raise CompilationError(
                f"Row search is not supported for the '{self.dialect.name}' dialect."
            )
        limit, offset = self._resolve_limit_offset()
        self._unpaged = True
        inner_sql, inner_params, _, _ = self.compile(context)
        names = self.select_column_names
        if not names or "*" in names:
            raise CompilationError(
                "Row search needs named columns; a query that selects * has none to search."
            )
        pattern = (
            "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        )
        matches = " OR ".join(
            f"{self.dialect.format_ilike(f'CAST({self.dialect.quote_alias(name)} AS {cast_type})')} ESCAPE '!'"
            for name in names
        )
        search_params = [pattern] * len(names)
        where = f"WHERE {matches}"
        page_sql, page_params = self.dialect.format_limit_offset(limit, offset)
        main_sql = f"SELECT * FROM ({inner_sql}) AS qb_rows {where} {page_sql}"
        count_sql = f"SELECT COUNT(*) FROM ({inner_sql}) AS qb_rows {where}"
        return (
            main_sql,
            [*inner_params, *search_params, *page_params],
            count_sql,
            [*inner_params, *search_params],
        )

    # ---- small shared helpers ---------------------------------------
    def _sub_compile(
        self, sub_spec: Any, *, inner: bool = True, as_dict: bool = True
    ) -> tuple[str, list[Any]]:
        """Compile a nested spec (subquery / CTE / set-operation body)."""
        if as_dict and not isinstance(sub_spec, dict):
            sub_spec = sub_spec.__dict__
        sub_compiler = QueryCompiler(
            sub_spec,
            schema=self.schema,
            user_id=self.user_id,
            force_user_filter=self.force_user_filter,
            tenant_id=self.tenant_id,
            dialect=self.dialect,
            ownership_paths=self.ownership_paths,
            max_limit=self.max_limit,
            allow_unknown_keys=True,
            capabilities=self.capabilities,
            semantic_models=self.semantic_models,
            inner=inner,
            param_counter=self._param_counter,
            custom_operators=self.custom_operators,
        )
        sub_sql, sub_params, _, _ = sub_compiler.compile()
        return sub_sql, sub_params

    def _qualified(self, alias: str, column: str) -> str:
        q = self.dialect.quote_identifier
        return f"{q(alias)}.{q(column)}"

    def _append_ownership_predicate(self, alias: str, table: str) -> None:
        try:
            predicate = resolve_ownership_predicate(
                self.dialect,
                self.tables_meta,
                alias,
                table,
                self.user_id,
                self.params,
                self._ownership_alias_counter,
                self.ownership_paths,
            )
        except SecurityError as e:
            raise CompilationError(str(e)) from e
        self.where_clauses.append(predicate)

    # ---- FROM / base table ------------------------------------------
    def _compile_from(self) -> None:
        base_table = self.spec.get("table")
        if not base_table:
            raise CompilationError(
                "Missing required 'table' parameter in query specification."
            )
        self._base_table = base_table
        self._from_params = []
        self._is_subquery_from = isinstance(base_table, dict) or hasattr(
            base_table, "__dict__"
        )
        if self._is_subquery_from:
            sub_dict = (
                base_table if isinstance(base_table, dict) else base_table.__dict__
            )
            if "subquery" in sub_dict and "table" not in sub_dict:
                sub_target = sub_dict["subquery"]
                explicit_alias = sub_dict.get("alias")
            else:
                sub_target = base_table
                explicit_alias = (
                    sub_dict.get("alias") if isinstance(sub_dict, dict) else None
                )
            sub_sql, self._from_params = self._sub_compile(sub_target)
            self._clean_base = str(explicit_alias) if explicit_alias else "subquery"
            self._base_alias = (
                str(explicit_alias) if explicit_alias else self._generate_unique_alias()
            )
            self.table_aliases[self._base_alias] = self._base_alias
            self.table_aliases[self._clean_base] = self._base_alias
            self.table_aliases["subquery"] = self._base_alias
            self._from_str = (
                f"FROM ({sub_sql}) {getattr(self.dialect, 'subquery_alias_keyword', 'AS ')}"
                f"{self.dialect.quote_identifier(self._base_alias)}"
            )
            return

        self._clean_base = base_table.split(".")[-1]
        if (
            self.tables_meta
            and self._clean_base not in self.tables_meta
            and base_table not in self.tables_meta
        ):
            raise CompilationError(
                f"Invalid or missing base table in schema: '{base_table}'"
            )
        self._base_alias = self._get_alias(self._clean_base, default_alias="t1")
        self.table_aliases[base_table] = self._base_alias
        if not self.dialect.supports_table_aliases:
            self._from_str = f"FROM {self.dialect.quote_identifier(base_table)}"
            return
        self._from_str = f"FROM {self.dialect.quote_identifier(base_table)} {self.dialect.quote_identifier(self._base_alias)}"

    @staticmethod
    def _has_id(val: Any) -> bool:
        return val is not None and val != "" and val is not False

    def _compile_base_isolation(self) -> None:
        """User / tenant isolation on the base table (skipped for a subquery FROM)."""
        if self._is_subquery_from:
            return
        if self.force_user_filter and self._has_id(self.user_id):
            self._append_ownership_predicate(self._base_alias, self._clean_base)

        if not self._has_id(self.tenant_id):
            return
        tbl_info = self.tables_meta.get(self._base_table) or self.tables_meta.get(
            self._clean_base, {}
        )
        cols = [
            c["name"] if isinstance(c, dict) else str(c)
            for c in tbl_info.get("columns", [])
        ]
        if "client_id" in cols or "tenant_id" in cols:
            col_name = "client_id" if "client_id" in cols else "tenant_id"
        elif self.tables_meta:
            raise CompilationError(
                f"Table '{self._clean_base}' does not have a client_id or tenant_id column for tenant isolation."
            )
        else:
            # Default fallback when no schema metadata dictionary is provided
            col_name = "tenant_id"
        self.where_clauses.append(
            f"{self._qualified(self._base_alias, col_name)} = {self.dialect.placeholder}"
        )
        self.params.append(self.tenant_id)

    def _compile_join_isolation(self) -> None:
        """User ownership isolation on joined tables."""
        if not (self.force_user_filter and self._has_id(self.user_id)):
            return
        for target_alias, clean_target in self._joined_targets:
            self._append_ownership_predicate(target_alias, clean_target)

    # ---- JOINs -------------------------------------------------------
    def _compile_joins(self) -> None:
        for raw_join in self.spec.get("joins", []):
            join = (
                _public_attrs(raw_join) if hasattr(raw_join, "__dict__") else raw_join
            )
            self._compile_join(join)

    def _compile_join(self, join: dict[str, Any]) -> None:
        target_table = join.get("table")
        if not target_table:
            raise CompilationError("Missing join target 'table'.")

        clean_target = target_table.split(".")[-1]
        if (
            self.tables_meta
            and clean_target not in self.tables_meta
            and target_table not in self.tables_meta
        ):
            raise CompilationError(f"Invalid join table in schema: '{target_table}'")

        if not self.dialect.supports_table_aliases:
            raise CompilationError(
                f"The '{self.dialect.name}' dialect cannot compile joins "
                "(its SQL layer does not support table aliases)."
            )
        join_type = self._normalise_join_type(join.get("type", "left"))
        target_alias = self._resolve_join_alias(join, target_table, clean_target)
        on_conditions = self._join_on_conditions(join, clean_target, target_alias)
        on_clause_str = " AND ".join(on_conditions)
        self.join_clauses.append(
            f"{join_type} {self.dialect.quote_identifier(target_table)} {self.dialect.quote_identifier(target_alias)} ON {on_clause_str}"
        )
        self._joined_targets.append((target_alias, clean_target))

    @staticmethod
    def _normalise_join_type(raw_type: str) -> str:
        join_type = raw_type.upper()
        if not join_type.endswith("JOIN"):
            join_type = f"{join_type} JOIN"
        if not any(join_type.startswith(p) for p in ("INNER", "LEFT", "RIGHT", "FULL")):
            join_type = "LEFT JOIN"
        return join_type

    def _resolve_join_alias(
        self, join: dict[str, Any], target_table: str, clean_target: str
    ) -> str:
        explicit_alias = join.get("alias")
        if explicit_alias:
            _check_ident(explicit_alias, "join alias")
            alias_str = str(explicit_alias)
            self.table_aliases[alias_str] = alias_str
            if clean_target not in self.table_aliases:
                self.table_aliases[clean_target] = alias_str
            if target_table not in self.table_aliases:
                self.table_aliases[target_table] = alias_str
            return alias_str
        if clean_target in self.table_aliases or target_table in self.table_aliases:
            alias = self._generate_unique_alias()
            self.table_aliases[alias] = alias
            return alias
        return self._get_alias(clean_target)

    def _join_on_conditions(
        self, join: dict[str, Any], clean_target: str, target_alias: str
    ) -> list[str]:
        clean_base = self._clean_base
        on_spec = join.get("on", [])
        if on_spec:
            conditions = []
            for raw_cond in on_spec:
                cond = (
                    dict(raw_cond.__dict__)
                    if hasattr(raw_cond, "__dict__")
                    else raw_cond
                )
                _, _, quoted_left = self._resolve_column_ref(
                    cond.get("left"), clean_base
                )
                _, _, quoted_right = self._resolve_column_ref(
                    cond.get("right"), clean_target, target_alias=target_alias
                )
                conditions.append(f"{quoted_left} = {quoted_right}")
            return conditions

        left_col = join.get("left_col") or join.get("leftCol")
        right_col = join.get("right_col") or join.get("rightCol")
        if left_col and right_col:
            left_tbl = join.get("left_table") or join.get("leftTable") or clean_base
            left_clean = left_tbl.split(".")[-1]
            if (
                left_tbl not in self.table_aliases
                and left_clean not in self.table_aliases
                and left_tbl != clean_base
                and left_clean != clean_base
            ):
                raise CompilationError(
                    f"Join left_table '{left_tbl}' is not part of the query."
                )
            _, _, quoted_left = self._resolve_column_ref(left_col, left_tbl)
            _, _, quoted_right = self._resolve_column_ref(
                right_col, clean_target, target_alias=target_alias
            )
            return [f"{quoted_left} = {quoted_right}"]

        return [self._auto_join_condition(clean_target, target_alias)]

    def _auto_join_condition(self, clean_target: str, target_alias: str) -> str:
        """Automatic FK / relationship resolution for a join without ON."""
        clean_base = self._clean_base
        for rel in self.rel_meta:
            src = rel.get("source_table", "").split(".")[-1]
            tgt = rel.get("target_table", "").split(".")[-1]
            if (src == clean_base and tgt == clean_target) or (
                src == clean_target and tgt == clean_base
            ):
                q_src = self._qualified(self._base_alias, rel["source_column"])
                q_tgt = self._qualified(target_alias, rel["target_column"])
                return f"{q_src} = {q_tgt}"

        if self.schema:
            cond = find_best_join_condition(clean_base, clean_target, self.schema)
            l_table = cond["left_table"].split(".")[-1]
            l_alias = (
                self._base_alias
                if l_table == clean_base
                else self._get_alias(cond["left_table"])
            )
            q_l = self._qualified(l_alias, cond["left_col"])
            q_r = self._qualified(target_alias, cond["right_col"])
            return f"{q_l} = {q_r}"

        raise CompilationError(
            f"No join condition specified and no FK relationship found between '{clean_base}' and '{clean_target}'"
        )

    # ---- projections ---------------------------------------------------
    def _projection_specs(self) -> list[Any]:
        columns_spec = self.spec.get("columns", [])
        if columns_spec:
            return list(columns_spec)
        if isinstance(self._base_table, str):
            base_meta = self.tables_meta.get(self._base_table) or self.tables_meta.get(
                self._clean_base
            )
            if base_meta:
                return [
                    f"{self._clean_base}.{c['name'] if isinstance(c, dict) else str(c)}"
                    for c in base_meta.get("columns", [])
                ]
        return ["*"]

    def _add_select(
        self,
        expr: str,
        label: str,
        *,
        group_by: str | None = None,
        aliased: bool = True,
    ) -> None:
        """Append one SELECT item (``expr AS label``) and its output name."""
        if aliased:
            self.select_clause_items.append(
                f"{expr} AS {self.dialect.quote_alias(label)}"
            )
        else:
            self.select_clause_items.append(expr)
        self.select_column_names.append(label)
        if group_by is not None:
            self.group_by_items.append(group_by)
        elif aliased:
            self._aggregate_labels.add(label)

    def _compile_projections(self) -> None:
        for col_item in self._projection_specs():
            if isinstance(col_item, str):
                self._compile_string_column(col_item)
            else:
                alias = col_item.get("alias") if isinstance(col_item, dict) else None
                if isinstance(alias, str) and alias:
                    self._declared_aliases.add(alias)
                self._compile_dict_column(col_item)

    def _star_ref(self) -> str:
        if not self.dialect.supports_table_aliases:
            return "*"
        return f"{self.dialect.quote_identifier(self._base_alias)}.*"

    def _compile_string_column(self, col_item: str) -> None:
        if col_item == "*":
            self.select_clause_items.append(self._star_ref())
            self.select_column_names.append("*")
            return
        _, col_name, quoted_ref = self._resolve_column_ref(col_item, self._clean_base)
        if col_name == "*":
            self.select_clause_items.append(quoted_ref)
            self.select_column_names.append(col_item)
            return
        self._add_select(quoted_ref, col_item, group_by=quoted_ref)

    def _compile_dict_column(self, col_item: dict[str, Any]) -> None:
        case_when = col_item.get("case_when")
        if case_when is not None:
            params_before = len(self.params)
            case_body = self._compile_case_when(case_when, self._clean_base)
            case_params = list(self.params[params_before:])
            self._count_skip_lead += len(case_params)
            alias_label = (
                col_item.get("alias") or f"case_{len(self.select_clause_items) + 1}"
            )
            self._add_select(case_body, alias_label, group_by=case_body)
            if case_params:
                self._group_by_params.extend(case_params)
            return

        expr = col_item.get("expression") or col_item.get("raw_expression")
        if expr is not None:
            if not isinstance(expr, str) or not expr.strip():
                raise ValidationError("Column 'expression' must be a non-empty string.")

            is_semantic = bool(col_item.get("metric") or col_item.get("dimension"))
            if not is_semantic and self.capabilities:
                self.capabilities.require_feature("custom_expressions")

            from query_builder.ast_validator import validate_sql_ast

            val_res = validate_sql_ast(
                f"SELECT {expr} FROM {self.dialect.quote_identifier(self._clean_base or 't')}"
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Expression failed AST safety validation."]
                )
                raise CompilationError(
                    f"Expression failed AST safety validation: {'; '.join(violations)}"
                )

            expr_alias = (
                col_item.get("alias") or f"expr_{len(self.select_clause_items) + 1}"
            )
            import re

            if re.search(
                r"\b(SUM|COUNT|AVG|MIN|MAX|STRING_AGG|ARRAY_AGG|GROUP_CONCAT|LISTAGG|STDDEV|STDDEV_POP|STDDEV_SAMP|VARIANCE|VAR_POP|VAR_SAMP|MEDIAN|PERCENTILE_CONT|PERCENTILE_DISC|BOOL_AND|BOOL_OR|ANY_VALUE|BIT_AND|BIT_OR|BIT_XOR)\b",
                expr,
                re.IGNORECASE,
            ):
                self.has_aggregation = True
                self._add_select(expr, expr_alias)
            else:
                self._add_select(expr, expr_alias, group_by=expr)
            return

        raw_col_ref = col_item.get("column", col_item.get("name"))
        if not raw_col_ref or not isinstance(raw_col_ref, str):
            return
        agg = (col_item.get("agg") or col_item.get("aggregate") or "").lower()
        alias = col_item.get("alias")

        if raw_col_ref == "*":
            self._compile_star_column(agg, alias)
            return

        _, col_name, quoted_ref = self._resolve_column_ref(
            raw_col_ref,
            col_item.get("table")
            or col_item.get("tablePrefix")
            or col_item.get("table_prefix")
            or self._clean_base,
        )

        time_grain = (
            col_item.get("time_grain")
            or col_item.get("timeGrain")
            or col_item.get("grain")
        )
        if time_grain:
            from query_builder.semantic import expand_time_grain_sql

            self.has_aggregation = True
            time_expr = expand_time_grain_sql(
                quoted_ref, grain=str(time_grain), dialect=self.dialect.name
            )
            self._add_select(
                time_expr, alias or f"{col_name}_{time_grain}", group_by=time_expr
            )
            return

        if self._compile_column_metric(col_item, raw_col_ref, alias):
            return

        if col_item.get("masked"):
            strategy = col_item.get("masking_strategy", "redact")
            masked_expr = self.dialect.format_masking_expression(quoted_ref, strategy)
            self._add_select(
                masked_expr, alias or f"{raw_col_ref}_masked", group_by=masked_expr
            )
            return

        if agg in AGGREGATE_MAP:
            self.has_aggregation = True
            agg_expr = self._aggregate_template(agg).format(quoted_ref)
            self._add_select(
                agg_expr, alias or f"{agg}_{raw_col_ref.replace('.', '_')}"
            )
        else:
            self._add_select(quoted_ref, alias or raw_col_ref, group_by=quoted_ref)

    def _compile_star_column(self, agg: str, alias: str | None) -> None:
        if not agg:
            self.select_clause_items.append(self._star_ref())
            self.select_column_names.append("*")
        elif agg == "count":
            self.has_aggregation = True
            self._add_select("COUNT(*)", alias or "count_all")
        elif agg == "count_distinct":
            raise CompilationError("COUNT(DISTINCT *) is not supported.")
        else:
            raise CompilationError(f"Aggregate '{agg}' cannot be applied to '*'.")

    def _find_metric(self, name: str) -> Any:
        """Look a metric up in the supplied semantic models, then the global registry."""
        from query_builder.semantic import get_global_semantic_registry

        for sm in self.semantic_models.values():
            if hasattr(sm, "get_metric"):
                m_def = sm.get_metric(name)
                if m_def:
                    return m_def
        return get_global_semantic_registry().get_metric(name)

    def _compile_column_metric(
        self, col_item: dict[str, Any], raw_col_ref: str, alias: str | None
    ) -> bool:
        """Expand a semantic metric column; True when the column was consumed."""
        is_metric = bool(col_item.get("metric"))
        if not (
            is_metric
            or (
                self.semantic_models
                and any(
                    hasattr(sm, "get_metric") and sm.get_metric(raw_col_ref)
                    for sm in self.semantic_models.values()
                )
            )
        ):
            return False

        from query_builder.semantic import MetricDefinition, expand_metric_sql

        metric_name: str = (
            col_item["metric"]
            if isinstance(col_item.get("metric"), str)
            else raw_col_ref
        )
        m_def = None
        if isinstance(col_item.get("metric"), dict):
            m_def = MetricDefinition.from_dict(col_item["metric"])
        if not m_def:
            m_def = self._find_metric(metric_name)
        if not m_def:
            return False
        self.has_aggregation = True
        metric_sql = expand_metric_sql(m_def, dialect=self.dialect.name)
        self._add_select(metric_sql, alias or m_def.name)
        return True

    def _compile_top_level_metrics(self) -> None:
        top_metrics = self.spec.get("metrics", [])
        if not top_metrics:
            return
        from query_builder.semantic import MetricDefinition, expand_metric_sql

        for m_entry in top_metrics:
            m_def = None
            m_alias = None
            m_name: str | None
            if isinstance(m_entry, str):
                m_name = m_entry
            elif isinstance(m_entry, dict):
                m_name = m_entry.get("name") or m_entry.get("metric")
                m_alias = m_entry.get("alias")
                if "sql_expression" in m_entry or "sql" in m_entry:
                    m_def = MetricDefinition.from_dict(m_entry)
            else:
                continue

            if not m_def and m_name:
                m_def = self._find_metric(m_name)

            if m_def:
                self.has_aggregation = True
                metric_sql = expand_metric_sql(m_def, dialect=self.dialect.name)
                self._add_select(metric_sql, m_alias or m_def.name)

    # ---- vector / hybrid search ----------------------------------------
    @staticmethod
    def _search_spec_dict(search_spec: Any) -> dict[str, Any]:
        if hasattr(search_spec, "to_dict"):
            result: dict[str, Any] = search_spec.to_dict()
            return result
        return search_spec if isinstance(search_spec, dict) else search_spec.__dict__

    def _compile_vector_search(self) -> None:
        vs_spec = self.spec.get("vector_search")
        self.has_vector_search = False
        self.vector_distance_expr = None
        self._vector_include_dist = True
        self._vector_param_val = None
        self._vector_min_score = None
        if not vs_spec:
            return
        self.has_vector_search = True
        vs_dict = self._search_spec_dict(vs_spec)
        vec = vs_dict.get("vector", [])
        vs_col = vs_dict.get("column", "embedding")
        metric = str(vs_dict.get("metric", "cosine")).lower()
        self._vector_include_dist = vs_dict.get("include_distances", True)
        min_score = vs_dict.get("min_score")
        self._vector_min_score = float(min_score) if min_score is not None else None

        _, _, vs_quoted_ref = self._resolve_column_ref(
            vs_col, default_table=self._clean_base, target_alias=self._base_alias
        )
        dist_expr = self.dialect.format_vector_distance(vs_quoted_ref, metric=metric)
        self.vector_distance_expr = dist_expr
        self._vector_param_val = self.dialect.format_vector_param(vec)

        if self._vector_include_dist:
            self._add_select(dist_expr, "_distance")
            self.params.append(self._vector_param_val)
            self._count_skip_lead += 1

    def _compile_vector_where(self) -> None:
        if self.has_vector_search and self._vector_min_score is not None:
            self.where_clauses.append(
                f"{self.vector_distance_expr} <= {self.dialect.placeholder}"
            )
            self.params.append(self._vector_param_val)
            self.params.append(self._vector_min_score)

    def _compile_hybrid_search(self) -> None:
        hs_spec = self.spec.get("hybrid_search")
        self.has_hybrid_search = False
        self.hybrid_score_expr = None
        self._hybrid_include_scores = True
        self._hybrid_vector_param = None
        self._hybrid_text_param = None
        self._hybrid_text_quoted_refs = []
        if not hs_spec:
            return
        self.has_hybrid_search = True
        hs_dict = self._search_spec_dict(hs_spec)
        vec = hs_dict.get("vector", [])
        v_col = hs_dict.get("vector_column", "embedding")
        q_text = hs_dict.get("query_text", "")
        t_cols = hs_dict.get("text_columns", [])
        alpha = float(hs_dict.get("alpha", 0.5))
        fusion = str(hs_dict.get("fusion", "rrf")).lower()
        rrf_k = int(hs_dict.get("rrf_k", 60))
        self._hybrid_include_scores = hs_dict.get("include_scores", True)
        metric = str(hs_dict.get("metric", "cosine")).lower()

        _, _, vs_quoted_ref = self._resolve_column_ref(
            v_col, default_table=self._clean_base, target_alias=self._base_alias
        )
        self._hybrid_text_quoted_refs = [
            self._resolve_column_ref(
                tc, default_table=self._clean_base, target_alias=self._base_alias
            )[2]
            for tc in t_cols
        ]

        v_dist = self.dialect.format_vector_distance(vs_quoted_ref, metric=metric)
        t_score = self.dialect.format_text_search(self._hybrid_text_quoted_refs)

        self._hybrid_vector_param = self.dialect.format_vector_param(vec)
        self._hybrid_text_param = f"%{q_text}%" if q_text else "%"

        if fusion == "linear":
            score_expr = f"({alpha} * (1.0 / (1.0 + {v_dist})) + {round(1.0 - alpha, 4)} * ({t_score}))"
        else:  # rrf
            score_expr = (
                f"((1.0 / ({rrf_k} + DENSE_RANK() OVER (ORDER BY {v_dist} ASC))) + "
                f"(1.0 / ({rrf_k} + DENSE_RANK() OVER (ORDER BY ({t_score}) DESC))))"
            )

        self.hybrid_score_expr = score_expr
        if self._hybrid_include_scores:
            self._add_select(score_expr, "_score")
            self.params.append(self._hybrid_vector_param)
            self._count_skip_lead += 1
            if self._hybrid_text_quoted_refs:
                self.params.append(self._hybrid_text_param)
                self._count_skip_lead += 1

    # ---- window functions ----------------------------------------------
    def _compile_window_functions(self) -> None:
        for wf_item in self.spec.get("window_functions", []):
            if hasattr(wf_item, "__dict__"):
                wf = _public_attrs(wf_item)
            elif isinstance(wf_item, dict):
                wf = wf_item
            else:
                continue
            self._compile_window_function(wf)

    def _window_args(self, wf: dict[str, Any], wf_func: str) -> str:
        wf_args = wf.get("arguments", [])
        if wf_args == ["*"]:
            return "*"
        if wf_args:
            formatted_args = []
            for a in wf_args:
                if isinstance(a, str):
                    _, _, qa = self._resolve_column_ref(a, self._clean_base)
                    formatted_args.append(qa)
                else:
                    formatted_args.append(str(a))
            return ", ".join(formatted_args)
        return "*" if wf_func == "COUNT" else ""

    def _window_partition(self, wf: dict[str, Any]) -> str:
        wf_parts = wf.get("partition_by", [])
        if not wf_parts:
            return ""
        quoted_parts = [
            self._resolve_column_ref(p, self._clean_base)[2] for p in wf_parts
        ]
        return f"PARTITION BY {', '.join(quoted_parts)}"

    def _window_order(self, wf: dict[str, Any]) -> str:
        quoted_orders = []
        for raw_ord in wf.get("order_by", []) or []:
            ord_item = (
                dict(raw_ord.__dict__) if hasattr(raw_ord, "__dict__") else raw_ord
            )
            col_ref = ord_item.get("column")
            if not col_ref:
                continue
            direction = ord_item.get("direction", "ASC").upper()
            if direction not in ("ASC", "DESC"):
                direction = "ASC"
            prefix = (
                ord_item.get("table_prefix")
                or ord_item.get("tablePrefix")
                or self._clean_base
            )
            _, _, qo = self._resolve_column_ref(col_ref, prefix)
            quoted_orders.append(f"{qo} {direction}")
        return f"ORDER BY {', '.join(quoted_orders)}" if quoted_orders else ""

    def _window_frame(self, wf: dict[str, Any]) -> str:
        wf_frame = wf.get("frame")
        if not wf_frame:
            return ""
        if hasattr(wf_frame, "__dict__"):
            wf_frame = dict(wf_frame.__dict__)
        ftype = (wf_frame.get("frame_type") or "ROWS").upper()
        if ftype == "GROUPS" and not getattr(
            self.dialect, "supports_window_groups_frame", False
        ):
            raise CompilationError(
                f"Dialect '{self.dialect.name}' does not support GROUPS window frame specification."
            )
        start = (wf_frame.get("start") or "UNBOUNDED PRECEDING").upper()
        end = wf_frame.get("end")
        if end:
            frame_clause = f"{ftype} BETWEEN {start} AND {str(end).upper()}"
        else:
            frame_clause = f"{ftype} {start}"
        exclusion = wf_frame.get("exclusion")
        if exclusion:
            frame_clause = f"{frame_clause} EXCLUDE {str(exclusion).upper()}"
        return frame_clause

    def _compile_window_function(self, wf: dict[str, Any]) -> None:
        wf_func = str(wf.get("function", "")).strip().upper()
        if not wf_func:
            return
        args_str = self._window_args(wf, wf_func)
        part_clause = self._window_partition(wf)
        order_clause = self._window_order(wf)
        frame_clause = self._window_frame(wf)
        if (
            part_clause
            and not order_clause
            and not frame_clause
            and wf_func in _WHOLE_PARTITION_AGGREGATES
            and getattr(self.dialect, "window_partition_null_rows_dropped", False)
        ):
            first_part = self._resolve_column_ref(
                wf["partition_by"][0], self._clean_base
            )[2]
            order_clause = f"ORDER BY {first_part}"
            frame_clause = "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING"

        over_tokens = [tok for tok in (part_clause, order_clause, frame_clause) if tok]
        wf_expr = f"{wf_func}({args_str}) OVER ({' '.join(over_tokens)})"

        alias = wf.get("alias")
        if alias:
            self._add_select(wf_expr, alias)
        else:
            self._add_select(wf_expr, wf_func, aliased=False)

    # ---- WHERE filters ---------------------------------------------------
    @staticmethod
    def _paren_count(raw: Any, char: str) -> int:
        """Number of grouping parentheses a ``parenOpen`` / ``parenClose`` value asks for."""
        if isinstance(raw, bool):
            return 1
        if isinstance(raw, int):
            return max(raw, 0)
        return str(raw).count(char) or 1

    def _compile_filters(self) -> None:
        filter_join = str(self.spec.get("filter_join") or "AND").strip().upper()
        if filter_join not in ("AND", "OR"):
            filter_join = "AND"

        client_filter_tokens: list[str] = []
        # Policy-injected predicates (tenant / RLS) carry ``_enforced`` and are
        # emitted as standalone AND-ed WHERE clauses outside the client group.
        enforced_clauses: list[str] = []
        enforced_params: list[Any] = []
        client_params: list[Any] = []
        paren_depth = 0
        for raw_flt in self.spec.get("filters", []):
            flt = dict(raw_flt.__dict__) if hasattr(raw_flt, "__dict__") else raw_flt
            params_start = len(self.params)
            clause_str = self._compile_filter_clause(flt)
            if clause_str is None:
                continue

            seg = self.params[params_start:]
            del self.params[params_start:]
            if flt.get("_enforced") is True:
                enforced_clauses.append(clause_str)
                enforced_params.extend(seg)
                continue
            client_params.extend(seg)

            comb = flt.get("combiner") or filter_join
            comb = comb.strip().upper() if isinstance(comb, str) else filter_join
            if comb not in ("AND", "OR"):
                comb = filter_join

            open_p = ""
            raw_open = flt.get("parenOpen") or flt.get("paren_open")
            if raw_open:
                n_open = min(self._paren_count(raw_open, "("), 16)
                open_p = "(" * n_open
                paren_depth += n_open

            close_p = ""
            raw_close = flt.get("parenClose") or flt.get("paren_close")
            if raw_close:
                # Never close more groups than are open: an unbalanced ')' would
                # terminate the wrapping client group and let a trailing OR
                # escape the enforced (tenant/RLS) predicates.
                n_close = min(self._paren_count(raw_close, ")"), paren_depth)
                close_p = ")" * n_close
                paren_depth -= n_close

            token = f"{open_p}{clause_str}{close_p}"
            if client_filter_tokens:
                client_filter_tokens.append(f"{comb} {token}")
            else:
                client_filter_tokens.append(token)

        self.where_clauses.extend(enforced_clauses)
        self.params.extend(enforced_params)
        if client_filter_tokens:
            if paren_depth > 0:
                client_filter_tokens[-1] += ")" * paren_depth
            self.where_clauses.append(f"({' '.join(client_filter_tokens)})")
            self.params.extend(client_params)

    def _compile_filter_clause(self, flt: dict[str, Any]) -> str | None:
        """SQL for one filter (params appended to ``self.params``); None to skip it."""
        op = str(flt.get("op", flt.get("operator", "eq"))).strip().lower()
        val = flt.get("value")
        subquery = flt.get("subquery")
        col_ref = flt.get("column")

        is_subquery_filter = (
            subquery is not None
            or (isinstance(val, dict) and "table" in val)
            or (hasattr(val, "__dict__") and hasattr(val, "table"))
        )

        if not col_ref and op not in _EXISTS_OPS:
            return None

        if col_ref:
            prefix = (
                flt.get("tablePrefix")
                or flt.get("table_prefix")
                or flt.get("table")
                or self._clean_base
            )
            _, _, quoted_ref = self._resolve_column_ref(col_ref, prefix)
        else:
            quoted_ref = ""

        sub_spec = subquery if subquery is not None else val
        not_pfx = "NOT " if "not" in op else ""

        if op in _EXISTS_OPS:
            if not is_subquery_filter:
                raise CompilationError("EXISTS filter requires a nested subquery.")
            sub_sql, sub_params = self._sub_compile(sub_spec)
            self.params.extend(sub_params)
            return f"{not_pfx}EXISTS ({sub_sql})"

        if val is None and not is_subquery_filter and op in ("eq", "=", "neq", "!="):
            return (
                f"{quoted_ref} IS NULL"
                if op in ("eq", "=")
                else f"{quoted_ref} IS NOT NULL"
            )
        if op in ("is_null", "is null"):
            return f"{quoted_ref} IS NULL"
        if op in ("is_not_null", "is not null"):
            return f"{quoted_ref} IS NOT NULL"

        if is_subquery_filter and op in ("in", "not in", "not_in"):
            sub_sql, sub_params = self._sub_compile(sub_spec)
            self.params.extend(sub_params)
            return f"{quoted_ref} {not_pfx}IN ({sub_sql})"
        if is_subquery_filter and op in OPERATOR_MAP:
            sub_sql, sub_params = self._sub_compile(sub_spec)
            self.params.extend(sub_params)
            return f"{quoted_ref} {self._sql_op(op)} ({sub_sql})"

        if op in OPERATOR_MAP:
            self.params.append(val)
            return f"{quoted_ref} {self._sql_op(op)} {self.dialect.placeholder}"

        if op in _SUBSTRING_OPS:
            kind, negated = _SUBSTRING_OPS[op]
            expr = self.dialect.format_substring_match(quoted_ref)
            self.params.append(self.dialect.substring_param(kind, val))
            return f"NOT ({expr})" if negated else expr

        if op in ("like", "not_like", "not like"):
            self.params.append(f"{val}")
            if "not" in op:
                return f"{quoted_ref} NOT LIKE {self.dialect.placeholder}"
            return self.dialect.format_like(quoted_ref)
        if op in ("ilike", "not_ilike", "not ilike"):
            self.params.append(f"{val}")
            if "not" in op:
                return f"NOT ({self.dialect.format_ilike(quoted_ref)})"
            return self.dialect.format_ilike(quoted_ref)

        if op in ("in", "not in", "not_in"):
            return self._compile_in_filter(quoted_ref, op, val)
        if op in ("between", "not_between", "not between"):
            return self._compile_between_filter(quoted_ref, op, val)
        if self.custom_operators and op in self.custom_operators:
            return self._compile_custom_filter(quoted_ref, op, val)
        with _CUSTOM_FILTER_OPERATORS_LOCK:
            if op in _CUSTOM_FILTER_OPERATORS:
                return self._compile_custom_filter(quoted_ref, op, val)
        raise CompilationError(f"Unsupported filter operator: '{op}'")

    def _compile_in_filter(self, quoted_ref: str, op: str, val: Any) -> str:
        if isinstance(val, (list, tuple, set)):
            val_list = list(val)
        elif isinstance(val, str):
            val_list = [v.strip() for v in val.split(",") if v.strip()]
        else:
            val_list = [val]

        negated = "not" in op
        if len(val_list) == 0:
            return "1 = 1" if negated else "1 = 0"
        if len(val_list) > MAX_IN_VALUES:
            raise CompilationError(
                f"IN clause value count ({len(val_list)}) exceeds maximum limit of {MAX_IN_VALUES}."
            )
        non_null_vals = [v for v in val_list if v is not None]
        if negated:
            if not non_null_vals:
                return "1 = 0"
            placeholders = ", ".join([self.dialect.placeholder] * len(non_null_vals))
            self.params.extend(non_null_vals)
            return (
                f"({quoted_ref} NOT IN ({placeholders}) AND {quoted_ref} IS NOT NULL)"
            )

        has_none = len(non_null_vals) != len(val_list)
        if has_none and non_null_vals:
            placeholders = ", ".join([self.dialect.placeholder] * len(non_null_vals))
            self.params.extend(non_null_vals)
            return f"({quoted_ref} IN ({placeholders}) OR {quoted_ref} IS NULL)"
        if has_none:
            return f"{quoted_ref} IS NULL"
        placeholders = ", ".join([self.dialect.placeholder] * len(val_list))
        self.params.extend(val_list)
        return f"{quoted_ref} IN ({placeholders})"

    def _compile_between_filter(self, quoted_ref: str, op: str, val: Any) -> str:
        if isinstance(val, (list, tuple)) and len(val) == 2:
            p0, p1 = val[0], val[1]
        elif isinstance(val, str) and " AND " in val:
            p0, p1 = (s.strip() for s in val.split(" AND ", 1))
        elif isinstance(val, str) and "," in val:
            p0, p1 = (s.strip() for s in val.split(",", 1))
        else:
            raise CompilationError("BETWEEN filter requires exactly 2 bounds.")
        not_pfx = "NOT " if "not" in op else ""
        self.params.extend([p0, p1])
        return f"{quoted_ref} {not_pfx}BETWEEN {self.dialect.placeholder} AND {self.dialect.placeholder}"

    def _compile_custom_filter(self, quoted_ref: str, op: str, val: Any) -> str:
        handler = None
        if self.custom_operators and op in self.custom_operators:
            handler = self.custom_operators[op]
        else:
            with _CUSTOM_FILTER_OPERATORS_LOCK:
                handler = _CUSTOM_FILTER_OPERATORS.get(op)
        if handler is None:
            raise CompilationError(f"Unsupported filter operator: '{op}'")
        res = handler(quoted_ref, val, self.dialect)
        if isinstance(res, tuple):
            clause_str, new_params = res
            if isinstance(new_params, (list, tuple)):
                self.params.extend(new_params)
            else:
                self.params.append(new_params)
            return clause_str
        if isinstance(res, str):
            return res
        raise CompilationError(
            f"Custom filter operator '{op}' returned invalid result: {type(res).__name__}"
        )

    # ---- HAVING / ORDER BY -------------------------------------------------
    def _compile_having(self) -> None:
        for raw_hvg in self.spec.get("having", []):
            hvg = dict(raw_hvg.__dict__) if hasattr(raw_hvg, "__dict__") else raw_hvg

            col_ref = hvg.get("column")
            raw_agg = hvg.get("agg") or hvg.get("aggregate")
            if col_ref and col_ref != "*":
                for c in self.spec.get("columns", []):
                    c_dict = dict(c.__dict__) if hasattr(c, "__dict__") else c
                    if (
                        isinstance(c_dict, dict)
                        and c_dict.get("alias") == col_ref
                        and c_dict.get("column")
                    ):
                        col_ref = c_dict["column"]
                        if not raw_agg and c_dict.get("agg"):
                            raw_agg = c_dict["agg"]
                        break
            agg = str(raw_agg or "count").lower()
            op = str(hvg.get("op", hvg.get("operator", "gt"))).lower()
            val = hvg.get("value")

            prefix = (
                hvg.get("tablePrefix")
                or hvg.get("table_prefix")
                or hvg.get("table")
                or self._clean_base
            )

            if col_ref == "*":
                if agg != "count":
                    raise CompilationError(
                        f"Aggregate '{agg}' cannot be applied to '*' in HAVING."
                    )
                agg_expr = "COUNT(*)"
            else:
                _, _, quoted_ref = self._resolve_column_ref(col_ref, prefix)
                if agg not in AGGREGATE_MAP:
                    continue
                agg_expr = self._aggregate_template(agg).format(quoted_ref)

            if op not in OPERATOR_MAP:
                continue
            self.having_clauses.append(
                f"{agg_expr} {self._sql_op(op)} {self.dialect.format_having_placeholder(val)}"
            )
            self.params.append(val)

    def _compile_order_by(self) -> None:
        for raw_ord in self.spec.get("order_by", []):
            ord_item = (
                dict(raw_ord.__dict__) if hasattr(raw_ord, "__dict__") else raw_ord
            )

            col_ref = ord_item.get("column")
            if not col_ref:
                continue
            direction = ord_item.get("direction", "ASC").upper()
            if direction not in ("ASC", "DESC"):
                direction = "ASC"

            raw_nulls = ord_item.get("nulls")
            nulls_suffix = ""
            if isinstance(raw_nulls, str):
                norm_nulls = raw_nulls.strip().upper()
                if norm_nulls in ("FIRST", "NULLS FIRST"):
                    nulls_suffix = " NULLS FIRST"
                elif norm_nulls in ("LAST", "NULLS LAST"):
                    nulls_suffix = " NULLS LAST"

            prefix = (
                ord_item.get("tablePrefix")
                or ord_item.get("table_prefix")
                or ord_item.get("table")
                or self._clean_base
            )
            unprefixed = not (
                ord_item.get("tablePrefix")
                or ord_item.get("table_prefix")
                or ord_item.get("table")
            )
            if unprefixed and (
                col_ref in self._aggregate_labels
                or (
                    col_ref in self._declared_aliases
                    and not self._base_has_column(col_ref)
                )
            ):
                # An aggregate has no column to qualify, and an alias is not a column of any table: ORDER BY names the
                # output label. A name that is a real column of the base table keeps meaning that column.
                self.order_by_items.append(
                    f"{self.dialect.quote_alias(col_ref)} {direction}{nulls_suffix}"
                )
                continue
            _, _, quoted_ref = self._resolve_column_ref(col_ref, prefix)
            quoted_ref = self._distinct_order_ref(quoted_ref)
            self.order_by_items.append(f"{quoted_ref} {direction}{nulls_suffix}")

    def _base_has_column(self, name: str) -> bool:
        """Whether the schema lists ``name`` as a column of the base table (an unprefixed ORDER BY name is read there)."""
        meta = self.tables_meta.get(self._clean_base) or self.tables_meta.get(
            str(self._base_table)
        )
        columns = meta.get("columns", []) if isinstance(meta, dict) else []
        return any(
            (c.get("name") if isinstance(c, dict) else str(c)) == name for c in columns
        )

    def _distinct_order_ref(self, quoted_ref: str) -> str:
        """Order by the select alias under ``SELECT DISTINCT`` on engines that require it.

        Only a select item that is exactly ``<quoted_ref> AS <alias>`` is rewritten, so the
        ordering is unchanged; any other dialect keeps the qualified column reference.
        """
        if not (
            getattr(self.dialect, "distinct_order_by_alias", False)
            and self.spec.get("distinct", False)
            and not self.has_aggregation
        ):
            return quoted_ref
        prefix = f"{quoted_ref} AS "
        for item in self.select_clause_items:
            if item.startswith(prefix):
                return item[len(prefix) :]
        return quoted_ref

    # ---- GROUP BY ----------------------------------------------------------
    def _grouping_columns(self, key: str) -> list[str] | None:
        """Explicit ``columns`` of a rollup / cube spec (dict or attribute object)."""
        group_spec = self.spec.get(key)
        cols = getattr(group_spec, "columns", None) if group_spec else None
        if cols is None and isinstance(group_spec, dict):
            cols = group_spec.get("columns")
        return cols

    def _quoted_columns(self, columns: Any) -> list[str]:
        return [self._resolve_column_ref(c, self._clean_base)[2] for c in columns]

    def _build_group_by(self) -> str:
        spec = self.spec
        explicit_grouping = bool(
            spec.get("grouping_type")
            or spec.get("grouping_sets")
            or spec.get("rollup")
            or spec.get("cube")
        )
        has_having = bool(spec.get("having"))
        if not (self.has_aggregation or has_having or explicit_grouping):
            return ""
        if not (self.group_by_items or explicit_grouping):
            return ""

        g_type = (spec.get("grouping_type") or "").lower()
        implicit = self.group_by_items
        if g_type == "rollup" or spec.get("rollup"):
            return self._group_by_rollup_or_cube("ROLLUP", "rollup")
        if g_type == "cube" or spec.get("cube"):
            return self._group_by_rollup_or_cube("CUBE", "cube")
        if g_type == "grouping_sets" or spec.get("grouping_sets"):
            g_sets = spec.get("grouping_sets") or []
            if hasattr(g_sets, "sets"):
                g_sets = g_sets.sets
            formatted_sets = [f"({', '.join(self._quoted_columns(s))})" for s in g_sets]
            if formatted_sets:
                return f"GROUP BY GROUPING SETS({', '.join(formatted_sets)})"
        if implicit:
            return f"GROUP BY {', '.join(implicit)}"
        return ""

    def _group_by_rollup_or_cube(self, keyword: str, key: str) -> str:
        cols = self._grouping_columns(key)
        if cols:
            return f"GROUP BY {keyword}({', '.join(self._quoted_columns(cols))})"
        if self.group_by_items:
            return f"GROUP BY {keyword}({', '.join(self.group_by_items)})"
        return ""

    # ---- ORDER BY clause / pagination ----------------------------------------
    def _build_order_by_clause(self) -> str:
        requires_order = getattr(
            self.dialect, "requires_order_by_for_pagination", False
        )
        if not self.order_by_items and self.has_vector_search:
            if self._vector_include_dist:
                return f"ORDER BY {self.dialect.quote_alias('_distance')} ASC"
            self.params.append(self._vector_param_val)
            return f"ORDER BY {self.vector_distance_expr} ASC"
        if not self.order_by_items and self.has_hybrid_search:
            if self._hybrid_include_scores:
                return f"ORDER BY {self.dialect.quote_alias('_score')} DESC"
            self.params.append(self._hybrid_vector_param)
            if self._hybrid_text_quoted_refs:
                self.params.append(self._hybrid_text_param)
            return f"ORDER BY {self.hybrid_score_expr} DESC"
        if requires_order and self._unpaginated_nested():
            # SQL Server rejects ORDER BY in a subquery/CTE unless TOP/OFFSET is
            # present, and an unpaginated nested query needs none.
            return ""
        if requires_order and not self.order_by_items:
            return "ORDER BY (SELECT NULL)"
        if self.order_by_items:
            return f"ORDER BY {', '.join(self.order_by_items)}"
        return ""

    def _resolve_limit_offset(self) -> tuple[int, int]:
        raw_limit = self.spec.get("limit")
        limit_val = int(raw_limit) if raw_limit is not None else 50
        if self.has_vector_search or self.has_hybrid_search:
            search_spec_val = self.spec.get("vector_search") or self.spec.get(
                "hybrid_search"
            )
            if isinstance(search_spec_val, dict):
                top_k_val = int(search_spec_val.get("top_k", 10))
            elif hasattr(search_spec_val, "top_k"):
                top_k_val = int(getattr(search_spec_val, "top_k", 10))
            else:
                top_k_val = 10
            if "limit" not in self.spec or raw_limit is None:
                limit_val = top_k_val
            else:
                limit_val = min(limit_val, top_k_val)

        limit = min(limit_val, self.max_limit)
        raw_offset = self.spec.get("offset")
        offset = min(
            max(int(raw_offset) if raw_offset is not None else 0, 0), MAX_OFFSET
        )
        return limit, offset

    def _build_pagination(self) -> tuple[str, list[Any]]:
        limit, offset = self._resolve_limit_offset()
        if self._unpaginated_nested() or self._unpaged:
            return "", []
        limit_offset_str, limit_params = self.dialect.format_limit_offset(limit, offset)
        return limit_offset_str, limit_params

    # ---- final assembly ---------------------------------------------------------
    def _assemble_main_query(
        self,
        select_str: str,
        joins_str: str,
        where_str: str,
        group_by_str: str,
        having_str: str,
        order_by_str: str,
        limit_offset_str: str,
        limit_params: list[Any],
    ) -> tuple[str, list[Any]]:
        tail = [
            part
            for part in (joins_str, where_str, group_by_str, having_str, order_by_str)
            if part
        ]
        select_params = list(self.params[: self._count_skip_lead])
        post_from_params = list(self.params[self._count_skip_lead :])
        if getattr(self.dialect, "pagination_placement", "suffix") == "prefix":
            select_pfx = (
                f"SELECT {limit_offset_str} " if limit_offset_str else "SELECT "
            )
            parts = [f"{select_pfx}{select_str}", self._from_str, *tail]
            return "\n".join(parts), (
                limit_params + select_params + self._from_params + post_from_params
            )
        parts = [f"SELECT {select_str}", self._from_str, *tail]
        if limit_offset_str:
            parts.append(limit_offset_str)
        return (
            "\n".join(parts),
            select_params + self._from_params + post_from_params + limit_params,
        )

    def _build_count_query(
        self, joins_str: str, where_str: str, group_by_str: str, having_str: str
    ) -> tuple[str, list[Any]]:
        base_parts = [p for p in (joins_str, where_str) if p]
        if group_by_str or having_str:
            # derived-table columns need a name (SQL Server error 8155)
            subquery_parts = [
                "SELECT 1 AS qb_one",
                self._from_str,
                *base_parts,
            ]
            if group_by_str:
                subquery_parts.append(group_by_str)
            if having_str:
                subquery_parts.append(having_str)
            count_sql = (
                f"SELECT COUNT(*) FROM ({' '.join(subquery_parts)}) "
                f"{getattr(self.dialect, 'subquery_alias_keyword', 'AS ')}count_subquery"
            )
        else:
            count_sql = "\n".join(["SELECT COUNT(*)", self._from_str, *base_parts])

        count_params = self._from_params + list(
            self.params[self._count_skip_lead : self._count_params_end]
        )
        return count_sql, count_params

    # ---- CTEs / set operations -----------------------------------------------------
    def _compile_ctes(self) -> tuple[str, list[Any]]:
        """Returns the ``WITH ...`` prefix (with trailing newline) and its params."""
        ctes_spec = self.spec.get("ctes") or []
        if not ctes_spec:
            return "", []
        has_recursive = any(
            (
                c.get("recursive")
                if isinstance(c, dict)
                else getattr(c, "recursive", False)
            )
            for c in ctes_spec
        )
        with_kw = "WITH RECURSIVE " if has_recursive else "WITH "
        cte_params: list[Any] = []
        compiled_ctes: list[str] = []
        for cte in ctes_spec:
            if hasattr(cte, "__dict__"):
                cte_dict = _public_attrs(cte)
            elif isinstance(cte, dict):
                cte_dict = cte
            else:
                raise CompilationError(f"Invalid CTE item type: {type(cte).__name__}")
            c_name: Any = cte_dict.get("name")
            c_cols = cte_dict.get("columns", [])
            c_mat = cte_dict.get("materialized")
            c_query = cte_dict.get("query")
            if isinstance(c_query, dict):
                inner_query_spec = c_query
            elif hasattr(c_query, "__dict__"):
                inner_query_spec = _public_attrs(c_query)
            else:
                raise CompilationError(
                    f"CTE '{c_name}' query must be a QuerySpec or dict."
                )

            inner_sql, inner_params = self._sub_compile(inner_query_spec)
            cte_params.extend(inner_params)

            cols_clause = (
                f" ({', '.join(self.dialect.quote_identifier(c) for c in c_cols)})"
                if c_cols
                else ""
            )
            mat_clause = self.dialect.format_cte_materialized(c_mat)
            quoted_c_name = self.dialect.quote_identifier(c_name)
            compiled_ctes.append(
                f"{quoted_c_name}{cols_clause} AS {mat_clause}(\n{inner_sql}\n)"
            )
        return f"{with_kw}{', '.join(compiled_ctes)}\n", cte_params

    def _apply_set_operations(
        self, main_sql: str, main_params: list[Any]
    ) -> tuple[str, list[Any], str, list[Any]]:
        """UNION / INTERSECT / EXCEPT / MINUS: chain bodies and rebuild the count query."""
        for so in self.spec.get("set_operations") or []:
            if hasattr(so, "__dict__"):
                so_dict = _public_attrs(so)
            elif isinstance(so, dict):
                so_dict = so
            else:
                raise CompilationError(
                    f"Invalid set operation item type: {type(so).__name__}"
                )
            op = str(so_dict.get("operation") or "UNION").upper().strip()
            sub_query = so_dict.get("query")
            if not sub_query:
                raise CompilationError(f"Set operation '{op}' is missing 'query'.")
            sub_sql, sub_params = self._sub_compile(
                sub_query, inner=False, as_dict=False
            )
            main_sql = f"{main_sql}\n{op}\n{sub_sql}"
            main_params = main_params + sub_params
        kw = getattr(self.dialect, "subquery_alias_keyword", "AS ")
        count_sql = f"SELECT COUNT(*) FROM (\n{main_sql}\n) {kw}set_op_count"
        return main_sql, main_params, count_sql, list(main_params)


AnalyticalCompiler = QueryCompiler
