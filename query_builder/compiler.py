"""
Declarative Query Compiler for SQL Explorer & Query Builder.
============================================================
Compiles declarative JSON query specifications into safe, parameterized SQL
with multi-dialect support (PostgreSQL, Snowflake, MSSQL, SQLite, MySQL),
automatic identifier quoting, tenant isolation injection, join resolution,
derived GROUP BY, HAVING, ordering, and pagination.
"""

from __future__ import annotations

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
    "time_grain",
    "grain",
    "metric",
    "format",
    "case_when",
    "expression",
}
ALLOWED_JOIN_KEYS = {
    "table",
    "type",
    "on",
    "left_table",
    "left_col",
    "right_col",
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
    "_enforced",
}
ALLOWED_HAVING_KEYS = {"column", "agg", "aggregate", "op", "operator", "value"}
ALLOWED_ORDER_BY_KEYS = {
    "column",
    "direction",
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
    _CUSTOM_FILTER_OPERATORS[clean_name] = handler
    ALLOWED_FILTER_OPS.add(clean_name)


def unregister_filter_operator(name: str) -> None:
    """
    Unregister a custom filter operator.
    """
    clean_name = name.lower().strip()
    _CUSTOM_FILTER_OPERATORS.pop(clean_name, None)
    if clean_name not in _BUILTIN_FILTER_OPS:
        ALLOWED_FILTER_OPS.discard(clean_name)


def list_filter_operators() -> list[str]:
    """
    Return a sorted list of all allowed filter operator names (built-in and custom).
    """
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


def validate_query_spec(spec: dict[str, Any], allow_unknown_keys: bool = False) -> None:
    """
    Validates an untrusted query specification dictionary against schema rules,
    acceptable keys, data types, and defensive DoS limits.
    """
    if not isinstance(spec, dict):
        raise ValidationError(
            f"Query spec must be a dictionary, got {type(spec).__name__}"
        )

    if not allow_unknown_keys:
        unknown = set(spec.keys()) - ALLOWED_SPEC_KEYS
        if unknown:
            raise ValidationError(
                f"Unexpected field(s) in query specification: {', '.join(sorted(unknown))}"
            )

    table = spec.get("table")
    if table is None:
        raise ValidationError(
            "Missing required 'table' parameter in query specification."
        )
    if isinstance(table, dict) or hasattr(table, "__dict__"):
        sub_dict = table if isinstance(table, dict) else table.__dict__
        validate_query_spec(sub_dict, allow_unknown_keys=allow_unknown_keys)
    else:
        _check_ident(table, "table")

    columns = spec.get("columns", [])
    if columns is not None and not isinstance(columns, (list, tuple)):
        raise ValidationError("Field 'columns' must be a list.")
    if columns and len(columns) > MAX_PROJECTIONS:
        raise ValidationError(
            f"Too many column projections: {len(columns)} exceeds maximum of {MAX_PROJECTIONS}."
        )
    for col in columns or []:
        if isinstance(col, str):
            if col == "*":
                pass
            elif col.endswith(".*"):
                _check_ident(col[:-2], "column table prefix")
            else:
                _check_ident(col, "column")
        elif isinstance(col, dict):
            if not allow_unknown_keys:
                unknown_col = set(col.keys()) - ALLOWED_COLUMN_KEYS
                if unknown_col:
                    raise ValidationError(
                        f"Unexpected field(s) in column specification: {', '.join(sorted(unknown_col))}"
                    )
            raw_col = col.get("column", col.get("name"))
            case_when = col.get("case_when")
            if case_when is not None:
                if hasattr(case_when, "__dict__"):
                    cw_dict = {
                        k: v
                        for k, v in case_when.__dict__.items()
                        if not k.startswith("_")
                    }
                elif isinstance(case_when, dict):
                    cw_dict = case_when
                else:
                    raise ValidationError(
                        "Field 'case_when' must be a dictionary or CaseWhenSpec."
                    )
                branches = cw_dict.get("branches", [])
                if not isinstance(branches, (list, tuple)) or len(branches) == 0:
                    raise ValidationError(
                        "'case_when' must contain a non-empty list of 'branches'."
                    )
                for b in branches:
                    if hasattr(b, "__dict__"):
                        b_dict = {
                            k: v for k, v in b.__dict__.items() if not k.startswith("_")
                        }
                    elif isinstance(b, dict):
                        b_dict = b
                    else:
                        raise ValidationError(
                            "Each branch in 'case_when' must be a dict or CaseWhenBranch."
                        )
                    if not b_dict.get("condition"):
                        raise ValidationError(
                            "Each branch in 'case_when' must have a 'condition'."
                        )

            if raw_col is None:
                if case_when is not None or col.get("expression") is not None:
                    pass
                else:
                    continue
            else:
                if isinstance(raw_col, str):
                    if raw_col == "*":
                        pass
                    elif raw_col.endswith(".*"):
                        _check_ident(raw_col[:-2], "column table prefix")
                    else:
                        _check_ident(raw_col, "column")
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

            time_grain = col.get("time_grain") or col.get("grain")
            if time_grain is not None:
                from query_builder.semantic import SUPPORTED_TIME_GRAINS

                if str(time_grain).lower() not in SUPPORTED_TIME_GRAINS:
                    raise ValidationError(f"Unsupported time grain: '{time_grain}'")
        else:
            raise ValidationError(
                f"Invalid column specification item type: {type(col).__name__}"
            )

    metrics = spec.get("metrics")
    if metrics is not None and not isinstance(metrics, (list, tuple)):
        raise ValidationError("Field 'metrics' must be a list.")

    joins = spec.get("joins", [])
    if joins is not None and not isinstance(joins, (list, tuple)):
        raise ValidationError("Field 'joins' must be a list.")
    if joins and len(joins) > MAX_JOINS:
        raise ValidationError(
            f"Too many joins: {len(joins)} exceeds maximum of {MAX_JOINS}."
        )
    for j in joins or []:
        if hasattr(j, "__dict__"):
            j_dict = {k: v for k, v in j.__dict__.items() if not k.startswith("_")}
        elif isinstance(j, dict):
            j_dict = j
        else:
            raise ValidationError(f"Invalid join item type: {type(j).__name__}")
        if not allow_unknown_keys:
            unknown_j = set(j_dict.keys()) - ALLOWED_JOIN_KEYS
            if unknown_j:
                raise ValidationError(
                    f"Unexpected field(s) in join specification: {', '.join(sorted(unknown_j))}"
                )
        j_tbl = j_dict.get("table")
        if j_tbl is not None:
            _check_ident(j_tbl, "join table")
        else:
            raise ValidationError("Missing join target 'table'.")
        if j_dict.get("alias"):
            _check_ident(j_dict["alias"], "join alias")
        if j_dict.get("left_table"):
            _check_ident(j_dict["left_table"], "join left_table")
        if j_dict.get("left_col"):
            _check_ident(j_dict["left_col"], "join left_col")
        if j_dict.get("right_col"):
            _check_ident(j_dict["right_col"], "join right_col")
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

    filters = spec.get("filters", [])
    if filters is not None and not isinstance(filters, (list, tuple)):
        raise ValidationError("Field 'filters' must be a list.")
    if filters and len(filters) > MAX_FILTERS:
        raise ValidationError(
            f"Too many filters: {len(filters)} exceeds maximum of {MAX_FILTERS}."
        )
    for flt in filters or []:
        if hasattr(flt, "__dict__"):
            flt_dict = {k: v for k, v in flt.__dict__.items() if not k.startswith("_")}
        elif isinstance(flt, dict):
            flt_dict = flt
        else:
            raise ValidationError(f"Invalid filter item type: {type(flt).__name__}")
        if not allow_unknown_keys:
            unknown_flt = set(flt_dict.keys()) - ALLOWED_FILTER_KEYS
            if unknown_flt:
                raise ValidationError(
                    f"Unexpected field(s) in filter specification: {', '.join(sorted(unknown_flt))}"
                )

        op = str(flt_dict.get("op", flt_dict.get("operator", "eq"))).strip().lower()
        if op not in ALLOWED_FILTER_OPS:
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
            validate_query_spec(sub_dict, allow_unknown_keys=allow_unknown_keys)
            flt_col = flt_dict.get("column")
            if flt_col is not None:
                _check_ident(flt_col, "filter column")
        elif op in ("exists", "not_exists", "not exists"):
            raise ValidationError("EXISTS filter requires a nested subquery.")
        else:
            flt_col = flt_dict.get("column")
            if flt_col is None:
                continue
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

    if (
        "filter_join" in spec
        and spec["filter_join"] is not None
        and not isinstance(spec["filter_join"], str)
    ):
        raise ValidationError("Field 'filter_join' must be a string.")

    having = spec.get("having", [])
    if having is not None and not isinstance(having, (list, tuple)):
        raise ValidationError("Field 'having' must be a list.")
    if having and len(having) > MAX_HAVING:
        raise ValidationError(
            f"Too many having specifications: {len(having)} exceeds maximum of {MAX_HAVING}."
        )
    for h in having or []:
        if hasattr(h, "__dict__"):
            h_dict = {k: v for k, v in h.__dict__.items() if not k.startswith("_")}
        elif isinstance(h, dict):
            h_dict = h
        else:
            raise ValidationError(f"Invalid having item type: {type(h).__name__}")
        if not allow_unknown_keys:
            unknown_h = set(h_dict.keys()) - ALLOWED_HAVING_KEYS
            if unknown_h:
                raise ValidationError(
                    f"Unexpected field(s) in having specification: {', '.join(sorted(unknown_h))}"
                )
        h_col = h_dict.get("column")
        if h_col is None:
            continue
        if h_col != "*":
            _check_ident(h_col, "having column")
        h_agg = str(h_dict.get("agg", h_dict.get("aggregate", "count"))).lower()
        if h_agg not in AGGREGATE_MAP:
            raise ValidationError(f"Unsupported having aggregate: '{h_agg}'")
        h_op = str(h_dict.get("op", h_dict.get("operator", "gt"))).lower()
        if h_op not in OPERATOR_MAP:
            raise ValidationError(f"Unsupported having operator: '{h_op}'")

    order_by = spec.get("order_by", [])
    if order_by is not None and not isinstance(order_by, (list, tuple)):
        raise ValidationError("Field 'order_by' must be a list.")
    if order_by and len(order_by) > MAX_ORDER_BY:
        raise ValidationError(
            f"Too many order by specifications: {len(order_by)} exceeds maximum of {MAX_ORDER_BY}."
        )
    for o in order_by or []:
        if hasattr(o, "__dict__"):
            o_dict = {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
        elif isinstance(o, dict):
            o_dict = o
        else:
            raise ValidationError(f"Invalid order_by item type: {type(o).__name__}")
        if not allow_unknown_keys:
            unknown_o = set(o_dict.keys()) - ALLOWED_ORDER_BY_KEYS
            if unknown_o:
                raise ValidationError(
                    f"Unexpected field(s) in order by specification: {', '.join(sorted(unknown_o))}"
                )
        o_col = o_dict.get("column")
        if o_col is None:
            continue
        _check_ident(o_col, "order_by column")
        o_pfx = (
            o_dict.get("tablePrefix")
            or o_dict.get("table_prefix")
            or o_dict.get("table")
        )
        if o_pfx is not None:
            _check_ident(o_pfx, "order_by table prefix")

    if "limit" in spec and spec["limit"] is not None:
        try:
            lim = int(spec["limit"])
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid limit value: {spec['limit']}") from e
        if lim < 0:
            raise ValidationError("Limit must be non-negative.")
        if lim > MAX_LIMIT:
            raise ValidationError(
                f"Limit ({lim}) exceeds maximum allowed limit of {MAX_LIMIT}."
            )

    if "offset" in spec and spec["offset"] is not None:
        try:
            off = int(spec["offset"])
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid offset value: {spec['offset']}") from e
        if off < 0:
            raise ValidationError("Offset must be non-negative.")
        if off > MAX_OFFSET:
            raise ValidationError(
                f"Offset ({off}) exceeds maximum allowed limit of {MAX_OFFSET}."
            )

    if (
        "distinct" in spec
        and spec["distinct"] is not None
        and not isinstance(spec["distinct"], bool)
    ):
        raise ValidationError("Field 'distinct' must be a boolean.")

    if "vector_search" in spec and spec["vector_search"] is not None:
        vs = spec["vector_search"]
        if isinstance(vs, dict):
            if not allow_unknown_keys:
                allowed_vs_keys = {
                    "vector",
                    "column",
                    "top_k",
                    "metric",
                    "include_distances",
                    "min_score",
                }
                unknown_vs = set(vs.keys()) - allowed_vs_keys
                if unknown_vs:
                    raise ValidationError(
                        f"Unexpected field(s) in vector_search specification: {', '.join(sorted(unknown_vs))}"
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

        if not isinstance(vec, (list, tuple)) or len(vec) == 0:
            raise ValidationError(
                "Field 'vector_search.vector' must be a non-empty list of numbers."
            )
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in vec):
            raise ValidationError(
                "All elements in 'vector_search.vector' must be numbers."
            )
        _check_ident(col, "vector_search column")
        if not isinstance(top_k, int) or top_k <= 0 or top_k > MAX_LIMIT:
            raise ValidationError(
                f"Field 'vector_search.top_k' must be an integer between 1 and {MAX_LIMIT}."
            )
        valid_metrics = {"cosine", "euclidean", "l2", "dot_product", "inner_product"}
        if str(metric).lower() not in valid_metrics:
            raise ValidationError(
                f"Invalid vector_search 'metric': '{metric}'. Must be one of {sorted(valid_metrics)}."
            )
        if min_score is not None and not isinstance(min_score, (int, float)):
            raise ValidationError(
                "Field 'vector_search.min_score' must be a number or None."
            )

    if "hybrid_search" in spec and spec["hybrid_search"] is not None:
        hs = spec["hybrid_search"]
        if isinstance(hs, dict):
            if not allow_unknown_keys:
                allowed_hs_keys = {
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
                unknown_hs = set(hs.keys()) - allowed_hs_keys
                if unknown_hs:
                    raise ValidationError(
                        f"Unexpected field(s) in hybrid_search specification: {', '.join(sorted(unknown_hs))}"
                    )
            vec = hs.get("vector")
            v_col = hs.get("vector_column", "embedding")
            q_text = hs.get("query_text", "")
            t_cols = hs.get("text_columns", [])
            alpha = hs.get("alpha", 0.5)
            fusion = hs.get("fusion", "rrf")
            rrf_k = hs.get("rrf_k", 60)
            top_k = hs.get("top_k", 10)
            metric = hs.get("metric", "cosine")
        elif hasattr(hs, "vector"):
            vec = hs.vector
            v_col = getattr(hs, "vector_column", "embedding")
            q_text = getattr(hs, "query_text", "")
            t_cols = getattr(hs, "text_columns", [])
            alpha = getattr(hs, "alpha", 0.5)
            fusion = getattr(hs, "fusion", "rrf")
            rrf_k = getattr(hs, "rrf_k", 60)
            top_k = getattr(hs, "top_k", 10)
            metric = getattr(hs, "metric", "cosine")
        else:
            raise ValidationError(
                "Field 'hybrid_search' must be a dictionary or HybridSearchSpec."
            )

        if not isinstance(vec, (list, tuple)) or len(vec) == 0:
            raise ValidationError(
                "Field 'hybrid_search.vector' must be a non-empty list of numbers."
            )
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in vec):
            raise ValidationError(
                "All elements in 'hybrid_search.vector' must be numbers."
            )
        _check_ident(v_col, "hybrid_search vector_column")

        if not isinstance(q_text, str):
            raise ValidationError("Field 'hybrid_search.query_text' must be a string.")

        if not isinstance(t_cols, (list, tuple)):
            raise ValidationError(
                "Field 'hybrid_search.text_columns' must be a list of column names."
            )
        for tc in t_cols:
            _check_ident(tc, "hybrid_search text_column")

        if not isinstance(alpha, (int, float)) or not (0.0 <= float(alpha) <= 1.0):
            raise ValidationError(
                "Field 'hybrid_search.alpha' must be a number between 0.0 and 1.0."
            )

        valid_fusions = {"rrf", "linear"}
        if str(fusion).lower() not in valid_fusions:
            raise ValidationError(
                f"Invalid hybrid_search 'fusion': '{fusion}'. Must be one of {sorted(valid_fusions)}."
            )

        if not isinstance(rrf_k, int) or rrf_k <= 0:
            raise ValidationError(
                "Field 'hybrid_search.rrf_k' must be a positive integer."
            )

        if not isinstance(top_k, int) or top_k <= 0 or top_k > MAX_LIMIT:
            raise ValidationError(
                f"Field 'hybrid_search.top_k' must be an integer between 1 and {MAX_LIMIT}."
            )

        valid_metrics = {"cosine", "euclidean", "l2", "dot_product", "inner_product"}
        if str(metric).lower() not in valid_metrics:
            raise ValidationError(
                f"Invalid hybrid_search 'metric': '{metric}'. Must be one of {sorted(valid_metrics)}."
            )

    if "ctes" in spec and spec["ctes"] is not None:
        ctes_val = spec["ctes"]
        if not isinstance(ctes_val, (list, tuple)):
            raise ValidationError("Field 'ctes' must be a list.")
        from query_builder.ast_validator import validate_cte_dag

        cte_res = validate_cte_dag(ctes_val)
        if not cte_res.get("valid", True):
            raise ValidationError(cte_res["violations"][0])

    if "window_functions" in spec and spec["window_functions"] is not None:
        wf_val = spec["window_functions"]
        if not isinstance(wf_val, (list, tuple)):
            raise ValidationError("Field 'window_functions' must be a list.")
        from query_builder.ast_validator import validate_window_function_spec

        for wf in wf_val:
            wf_res = validate_window_function_spec(wf)
            if not wf_res.get("valid", True):
                raise ValidationError(wf_res["violations"][0])

    if "set_operations" in spec and spec["set_operations"] is not None:
        so_val = spec["set_operations"]
        if not isinstance(so_val, (list, tuple)):
            raise ValidationError("Field 'set_operations' must be a list.")
        for so in so_val:
            if hasattr(so, "__dict__"):
                so_dict = {
                    k: v for k, v in so.__dict__.items() if not k.startswith("_")
                }
            elif isinstance(so, dict):
                so_dict = so
            else:
                raise ValidationError(
                    "Each set operation must be a dict or SetOperationSpec."
                )
            op = str(so_dict.get("operation", "UNION")).upper().strip()
            valid_ops = {"UNION", "UNION ALL", "INTERSECT", "EXCEPT", "MINUS"}
            if op not in valid_ops:
                raise ValidationError(
                    f"Invalid set operation: '{op}'. Must be one of {sorted(valid_ops)}."
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

    if "grouping_type" in spec and spec["grouping_type"] is not None:
        gt = str(spec["grouping_type"]).lower().strip()
        if gt not in {"standard", "rollup", "cube", "grouping_sets"}:
            raise ValidationError(
                f"Invalid 'grouping_type': '{gt}'. Must be one of 'standard', 'rollup', 'cube', 'grouping_sets'."
            )

    if "grouping_sets" in spec and spec["grouping_sets"] is not None:
        gs_val = spec["grouping_sets"]
        if not isinstance(gs_val, (list, tuple)) and not hasattr(gs_val, "sets"):
            raise ValidationError(
                "Field 'grouping_sets' must be a list of column lists."
            )

    if "rollup" in spec and spec["rollup"] is not None:
        r_val = spec["rollup"]
        if not isinstance(r_val, (dict, list, tuple)) and not hasattr(r_val, "columns"):
            raise ValidationError("Field 'rollup' must be a RollupSpec or dict.")

    if "cube" in spec and spec["cube"] is not None:
        c_val = spec["cube"]
        if not isinstance(c_val, (dict, list, tuple)) and not hasattr(c_val, "columns"):
            raise ValidationError("Field 'cube' must be a CubeSpec or dict.")

    if "pivot" in spec and spec["pivot"] is not None:
        p_val = spec["pivot"]
        if not isinstance(p_val, dict) and not hasattr(p_val, "column"):
            raise ValidationError("Field 'pivot' must be a PivotSpec or dict.")


class QueryCompiler:
    """
    Translates a declarative JSON QueryBuilderSpec into safe, parameterized SQL.
    Supports dialect switching, automatic join resolution, tenant/user isolation,
    and automatic COUNT subquery construction.
    """

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
    ) -> None:
        # Nested queries (CTE bodies, subqueries in FROM / IN / EXISTS) must not
        # get the implicit page LIMIT: it would silently truncate the inner
        # result set (and MySQL rejects LIMIT inside IN subqueries).
        self.inner = inner
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

            self.middleware = MiddlewarePipeline.ensure(middleware)
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
            validate_query_spec(self.spec, allow_unknown_keys=allow_unknown_keys)

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
        self._ownership_alias_counter = AliasCounter()

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
                if c.get("expression") or c.get("case_when"):
                    self.capabilities.require_feature("calculated_fields")
            elif hasattr(c, "expression") or hasattr(c, "case_when"):
                if getattr(c, "expression", None) or getattr(c, "case_when", None):
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
        self, col_ref: str, default_table: str, target_alias: str | None = None
    ) -> tuple[str, str, str]:
        """Resolves a column reference to (alias, col_name, quoted_column_ref)."""
        if not isinstance(col_ref, str) or not col_ref.strip():
            raise CompilationError(f"Invalid column reference: '{col_ref}'")
        if "." in col_ref:
            parts = col_ref.rsplit(".", 1)
            tbl = parts[0]
            col = parts[1]
        else:
            tbl = default_table
            col = col_ref

        clean_col = col.split(".")[-1]
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

        if clean_col == "*":
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
                sql_op = OPERATOR_MAP[op]
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

        base_table = self.spec.get("table")
        if not base_table:
            raise CompilationError(
                "Missing required 'table' parameter in query specification."
            )

        from_params: list[Any] = []
        is_subquery_from = isinstance(base_table, dict) or hasattr(
            base_table, "__dict__"
        )
        if is_subquery_from:
            sub_spec = (
                base_table if isinstance(base_table, dict) else base_table.__dict__
            )
            sub_compiler = QueryCompiler(
                sub_spec,
                schema=self.schema,
                dialect=self.dialect,
                middleware=None,
                allow_unknown_keys=True,
                inner=True,
            )
            sub_sql, from_params, _, _ = sub_compiler.compile()
            clean_base_table = "subquery"
            base_alias = self._generate_unique_alias()
            self.table_aliases[base_alias] = base_alias
            self.table_aliases[clean_base_table] = base_alias
            from_str = (
                f"FROM ({sub_sql}) AS {self.dialect.quote_identifier(base_alias)}"
            )
        else:
            clean_base_table = base_table.split(".")[-1]
            if (
                self.tables_meta
                and clean_base_table not in self.tables_meta
                and base_table not in self.tables_meta
            ):
                raise CompilationError(
                    f"Invalid or missing base table in schema: '{base_table}'"
                )
            base_alias = self._get_alias(clean_base_table, default_alias="t1")
            self.table_aliases[base_table] = base_alias
            from_str = f"FROM {self.dialect.quote_identifier(base_table)} {self.dialect.quote_identifier(base_alias)}"

        # 1. Base table user / tenant isolation (skip if base table is subquery)
        if not is_subquery_from:
            if self.force_user_filter and self.user_id:
                try:
                    predicate = resolve_ownership_predicate(
                        self.dialect,
                        self.tables_meta,
                        base_alias,
                        clean_base_table,
                        self.user_id,
                        self.params,
                        self._ownership_alias_counter,
                        self.ownership_paths,
                    )
                    self.where_clauses.append(predicate)
                except SecurityError as e:
                    raise CompilationError(str(e)) from e

            if self.tenant_id:
                tbl_info = self.tables_meta.get(base_table) or self.tables_meta.get(
                    clean_base_table, {}
                )
                cols = [
                    c["name"] if isinstance(c, dict) else str(c)
                    for c in tbl_info.get("columns", [])
                ]
                if "client_id" in cols or "tenant_id" in cols:
                    col_name = "client_id" if "client_id" in cols else "tenant_id"
                    self.where_clauses.append(
                        f"{self.dialect.quote_identifier(base_alias)}.{self.dialect.quote_identifier(col_name)} = {self.dialect.placeholder}"
                    )
                    self.params.append(self.tenant_id)
                elif self.tables_meta:
                    raise CompilationError(
                        f"Table '{clean_base_table}' does not have a client_id or tenant_id column for tenant isolation."
                    )
                else:
                    # Default fallback when no schema metadata dictionary is provided
                    self.where_clauses.append(
                        f"{self.dialect.quote_identifier(base_alias)}.{self.dialect.quote_identifier('tenant_id')} = {self.dialect.placeholder}"
                    )
                    self.params.append(self.tenant_id)

        # 2. Process Joins
        joins_spec = self.spec.get("joins", [])
        for raw_join in joins_spec:
            if hasattr(raw_join, "__dict__"):
                join = {
                    k: v for k, v in raw_join.__dict__.items() if not k.startswith("_")
                }
            else:
                join = raw_join

            target_table = join.get("table")
            if not target_table:
                raise CompilationError("Missing join target 'table'.")

            clean_target_table = target_table.split(".")[-1]
            if (
                self.tables_meta
                and clean_target_table not in self.tables_meta
                and target_table not in self.tables_meta
            ):
                raise CompilationError(
                    f"Invalid join table in schema: '{target_table}'"
                )

            join_type = join.get("type", "left").upper()
            if not join_type.endswith("JOIN"):
                join_type = f"{join_type} JOIN"
            if not any(
                join_type.startswith(p) for p in ("INNER", "LEFT", "RIGHT", "FULL")
            ):
                join_type = "LEFT JOIN"

            explicit_alias = join.get("alias")
            if explicit_alias:
                _check_ident(explicit_alias, "join alias")
                target_alias = explicit_alias
                self.table_aliases[explicit_alias] = explicit_alias
            elif (
                clean_target_table in self.table_aliases
                or target_table in self.table_aliases
            ):
                target_alias = self._generate_unique_alias()
                self.table_aliases[target_alias] = target_alias
            else:
                target_alias = self._get_alias(clean_target_table)

            on_conditions = []
            on_spec = join.get("on", [])

            if on_spec:
                for raw_cond in on_spec:
                    if hasattr(raw_cond, "__dict__"):
                        cond = {k: v for k, v in raw_cond.__dict__.items()}
                    else:
                        cond = raw_cond
                    left_ref = cond.get("left")
                    right_ref = cond.get("right")
                    _, _, quoted_left = self._resolve_column_ref(
                        left_ref, clean_base_table
                    )
                    _, _, quoted_right = self._resolve_column_ref(
                        right_ref, clean_target_table, target_alias=target_alias
                    )
                    on_conditions.append(f"{quoted_left} = {quoted_right}")
            elif join.get("left_col") and join.get("right_col"):
                left_tbl = join.get("left_table", clean_base_table)
                left_clean = left_tbl.split(".")[-1]
                if (
                    left_tbl not in self.table_aliases
                    and left_clean not in self.table_aliases
                    and left_tbl != clean_base_table
                    and left_clean != clean_base_table
                ):
                    raise CompilationError(
                        f"Join left_table '{left_tbl}' is not part of the query."
                    )
                _, _, quoted_left = self._resolve_column_ref(join["left_col"], left_tbl)
                _, _, quoted_right = self._resolve_column_ref(
                    join["right_col"], clean_target_table, target_alias=target_alias
                )
                on_conditions.append(f"{quoted_left} = {quoted_right}")
            else:
                # Automatic FK / Relationship resolution
                found_rel = False
                for rel in self.rel_meta:
                    src = rel.get("source_table", "").split(".")[-1]
                    tgt = rel.get("target_table", "").split(".")[-1]
                    if (src == clean_base_table and tgt == clean_target_table) or (
                        src == clean_target_table and tgt == clean_base_table
                    ):
                        src_alias = base_alias
                        tgt_alias = target_alias
                        q_src = f"{self.dialect.quote_identifier(src_alias)}.{self.dialect.quote_identifier(rel['source_column'])}"
                        q_tgt = f"{self.dialect.quote_identifier(tgt_alias)}.{self.dialect.quote_identifier(rel['target_column'])}"
                        on_conditions.append(f"{q_src} = {q_tgt}")
                        found_rel = True
                        break

                if not found_rel and self.schema:
                    cond = find_best_join_condition(
                        clean_base_table, clean_target_table, self.schema
                    )
                    l_table = cond["left_table"].split(".")[-1]
                    l_alias = (
                        base_alias
                        if l_table == clean_base_table
                        else self._get_alias(cond["left_table"])
                    )
                    r_alias = target_alias
                    q_l = f"{self.dialect.quote_identifier(l_alias)}.{self.dialect.quote_identifier(cond['left_col'])}"
                    q_r = f"{self.dialect.quote_identifier(r_alias)}.{self.dialect.quote_identifier(cond['right_col'])}"
                    on_conditions.append(f"{q_l} = {q_r}")
                    found_rel = True

                if not found_rel:
                    raise CompilationError(
                        f"No join condition specified and no FK relationship found between '{clean_base_table}' and '{clean_target_table}'"
                    )

            on_clause_str = " AND ".join(on_conditions)
            self.join_clauses.append(
                f"{join_type} {self.dialect.quote_identifier(target_table)} {self.dialect.quote_identifier(target_alias)} ON {on_clause_str}"
            )

            # Tenant isolation on joined table
            if self.force_user_filter and self.user_id:
                try:
                    predicate = resolve_ownership_predicate(
                        self.dialect,
                        self.tables_meta,
                        target_alias,
                        clean_target_table,
                        self.user_id,
                        self.params,
                        self._ownership_alias_counter,
                        self.ownership_paths,
                    )
                    self.where_clauses.append(predicate)
                except SecurityError as e:
                    raise CompilationError(str(e)) from e

        # 3. Process Columns (Projections)
        columns_spec = self.spec.get("columns", [])
        if not columns_spec:
            base_meta = self.tables_meta.get(base_table) or self.tables_meta.get(
                clean_base_table
            )
            if base_meta:
                columns_spec = [
                    f"{clean_base_table}.{c['name'] if isinstance(c, dict) else str(c)}"
                    for c in base_meta.get("columns", [])
                ]
            else:
                columns_spec = ["*"]

        for col_item in columns_spec:
            if isinstance(col_item, str):
                if col_item == "*":
                    self.select_clause_items.append(
                        f"{self.dialect.quote_identifier(base_alias)}.*"
                    )
                    self.select_column_names.append("*")
                    continue
                _, col_name, quoted_ref = self._resolve_column_ref(
                    col_item, clean_base_table
                )
                if col_name == "*":
                    self.select_clause_items.append(quoted_ref)
                    self.select_column_names.append(col_item)
                    continue
                self.select_clause_items.append(
                    f"{quoted_ref} AS {self.dialect.quote_alias(col_item)}"
                )
                self.select_column_names.append(col_item)
                self.group_by_items.append(quoted_ref)
            else:
                case_when = col_item.get("case_when")
                if case_when is not None:
                    case_body = self._compile_case_when(case_when, clean_base_table)
                    alias_label = (
                        col_item.get("alias")
                        or f"case_{len(self.select_clause_items) + 1}"
                    )
                    self.select_clause_items.append(
                        f"{case_body} AS {self.dialect.quote_alias(alias_label)}"
                    )
                    self.select_column_names.append(alias_label)
                    self.group_by_items.append(case_body)
                    continue

                raw_col_ref = col_item.get("column", col_item.get("name"))
                if not raw_col_ref or not isinstance(raw_col_ref, str):
                    continue
                agg = (col_item.get("agg") or col_item.get("aggregate") or "").lower()
                alias = col_item.get("alias")
                tbl = col_item.get("table", clean_base_table)

                if raw_col_ref == "*":
                    if agg:
                        if agg == "count":
                            self.has_aggregation = True
                            agg_expr = "COUNT(*)"
                            alias_label = alias or "count_all"
                            self.select_clause_items.append(
                                f"{agg_expr} AS {self.dialect.quote_alias(alias_label)}"
                            )
                            self.select_column_names.append(alias_label)
                        elif agg == "count_distinct":
                            raise CompilationError(
                                "COUNT(DISTINCT *) is not supported."
                            )
                        else:
                            raise CompilationError(
                                f"Aggregate '{agg}' cannot be applied to '*'."
                            )
                    else:
                        self.select_clause_items.append(
                            f"{self.dialect.quote_identifier(base_alias)}.*"
                        )
                        self.select_column_names.append("*")
                    continue

                _, col_name, quoted_ref = self._resolve_column_ref(raw_col_ref, tbl)

                time_grain = col_item.get("time_grain") or col_item.get("grain")
                if time_grain:
                    from query_builder.semantic import expand_time_grain_sql

                    time_expr = expand_time_grain_sql(
                        quoted_ref, grain=str(time_grain), dialect=self.dialect.name
                    )
                    alias_label = alias or f"{raw_col_ref}_{time_grain}"
                    self.select_clause_items.append(
                        f"{time_expr} AS {self.dialect.quote_alias(alias_label)}"
                    )
                    self.select_column_names.append(alias_label)
                    self.group_by_items.append(time_expr)
                    continue

                is_metric = bool(col_item.get("metric"))
                metric_name = (
                    col_item.get("metric")
                    if isinstance(col_item.get("metric"), str)
                    else raw_col_ref
                )
                if is_metric or (
                    self.semantic_models
                    and any(
                        hasattr(sm, "get_metric") and sm.get_metric(raw_col_ref)
                        for sm in self.semantic_models.values()
                    )
                ):
                    from query_builder.semantic import (
                        MetricDefinition,
                        expand_metric_sql,
                        get_global_semantic_registry,
                    )

                    m_def = None
                    if isinstance(col_item.get("metric"), dict):
                        m_def = MetricDefinition.from_dict(col_item["metric"])
                    if not m_def and self.semantic_models:
                        for sm in self.semantic_models.values():
                            if hasattr(sm, "get_metric"):
                                m_def = sm.get_metric(metric_name)
                                if m_def:
                                    break
                    if not m_def:
                        m_def = get_global_semantic_registry().get_metric(metric_name)
                    if m_def:
                        self.has_aggregation = True
                        metric_sql = expand_metric_sql(m_def, dialect=self.dialect.name)
                        alias_label = alias or m_def.name
                        self.select_clause_items.append(
                            f"{metric_sql} AS {self.dialect.quote_alias(alias_label)}"
                        )
                        self.select_column_names.append(alias_label)
                        continue

                if agg in AGGREGATE_MAP:
                    self.has_aggregation = True
                    agg_expr = self._aggregate_template(agg).format(quoted_ref)
                    alias_label = alias or f"{agg}_{raw_col_ref.replace('.', '_')}"
                    self.select_clause_items.append(
                        f"{agg_expr} AS {self.dialect.quote_alias(alias_label)}"
                    )
                    self.select_column_names.append(alias_label)
                else:
                    alias_label = alias or raw_col_ref
                    self.select_clause_items.append(
                        f"{quoted_ref} AS {self.dialect.quote_alias(alias_label)}"
                    )
                    self.select_column_names.append(alias_label)
                    self.group_by_items.append(quoted_ref)

        # 3.01. Process Top-Level Semantic Metrics
        top_metrics = self.spec.get("metrics", [])
        if top_metrics:
            from query_builder.semantic import (
                MetricDefinition,
                expand_metric_sql,
                get_global_semantic_registry,
            )

            for m_entry in top_metrics:
                m_def = None
                m_alias = None
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
                    for sm in self.semantic_models.values():
                        if hasattr(sm, "get_metric"):
                            m_def = sm.get_metric(m_name)
                            if m_def:
                                break
                    if not m_def:
                        m_def = get_global_semantic_registry().get_metric(m_name)

                if m_def:
                    self.has_aggregation = True
                    metric_sql = expand_metric_sql(m_def, dialect=self.dialect.name)
                    alias_label = m_alias or m_def.name
                    self.select_clause_items.append(
                        f"{metric_sql} AS {self.dialect.quote_alias(alias_label)}"
                    )
                    self.select_column_names.append(alias_label)

        # 3.1. Process Vector Search
        vs_spec = self.spec.get("vector_search")
        self.has_vector_search = False
        self.vector_distance_expr = None
        self._vector_include_dist = True
        self._vector_param_val = None
        if vs_spec:
            self.has_vector_search = True
            vs_dict = (
                vs_spec.to_dict()
                if hasattr(vs_spec, "to_dict")
                else (vs_spec if isinstance(vs_spec, dict) else vs_spec.__dict__)
            )
            vec = vs_dict.get("vector", [])
            vs_col = vs_dict.get("column", "embedding")
            metric = str(vs_dict.get("metric", "cosine")).lower()
            self._vector_include_dist = vs_dict.get("include_distances", True)
            min_score = vs_dict.get("min_score")

            _, _, vs_quoted_ref = self._resolve_column_ref(
                vs_col, default_table=clean_base_table, target_alias=base_alias
            )
            self.vector_distance_expr = self.dialect.format_vector_distance(
                vs_quoted_ref, metric=metric
            )
            self._vector_param_val = self.dialect.format_vector_param(vec)

            if self._vector_include_dist:
                dist_alias = "_distance"
                self.select_clause_items.append(
                    f"{self.vector_distance_expr} AS {self.dialect.quote_alias(dist_alias)}"
                )
                self.select_column_names.append(dist_alias)
                self.params.append(self._vector_param_val)
                self._count_skip_lead += 1

            if min_score is not None:
                self.where_clauses.append(
                    f"{self.vector_distance_expr} <= {self.dialect.placeholder}"
                )
                self.params.append(self._vector_param_val)
                self.params.append(float(min_score))

        # 3.2. Process Hybrid Search
        hs_spec = self.spec.get("hybrid_search")
        self.has_hybrid_search = False
        self.hybrid_score_expr = None
        self._hybrid_include_scores = True
        self._hybrid_vector_param = None
        self._hybrid_text_param = None
        self._hybrid_text_quoted_refs: list[str] = []
        if hs_spec:
            self.has_hybrid_search = True
            hs_dict = (
                hs_spec.to_dict()
                if hasattr(hs_spec, "to_dict")
                else (hs_spec if isinstance(hs_spec, dict) else hs_spec.__dict__)
            )
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
                v_col, default_table=clean_base_table, target_alias=base_alias
            )
            self._hybrid_text_quoted_refs = [
                self._resolve_column_ref(
                    tc, default_table=clean_base_table, target_alias=base_alias
                )[2]
                for tc in t_cols
            ]

            v_dist = self.dialect.format_vector_distance(vs_quoted_ref, metric=metric)
            t_score = self.dialect.format_text_search(self._hybrid_text_quoted_refs)

            self._hybrid_vector_param = self.dialect.format_vector_param(vec)
            self._hybrid_text_param = f"%{q_text}%" if q_text else "%"

            if fusion == "linear":
                self.hybrid_score_expr = f"({alpha} * (1.0 / (1.0 + {v_dist})) + {round(1.0 - alpha, 4)} * ({t_score}))"
            else:  # rrf
                self.hybrid_score_expr = (
                    f"((1.0 / ({rrf_k} + DENSE_RANK() OVER (ORDER BY {v_dist} ASC))) + "
                    f"(1.0 / ({rrf_k} + DENSE_RANK() OVER (ORDER BY ({t_score}) DESC))))"
                )

            if self._hybrid_include_scores:
                score_alias = "_score"
                self.select_clause_items.append(
                    f"{self.hybrid_score_expr} AS {self.dialect.quote_alias(score_alias)}"
                )
                self.select_column_names.append(score_alias)
                self.params.append(self._hybrid_vector_param)
                self._count_skip_lead += 1
                if self._hybrid_text_quoted_refs:
                    self.params.append(self._hybrid_text_param)
                    self._count_skip_lead += 1

        # 3b. Process Window Functions
        window_funcs_spec = self.spec.get("window_functions", [])
        for wf_item in window_funcs_spec:
            if hasattr(wf_item, "__dict__"):
                wf = {
                    k: v for k, v in wf_item.__dict__.items() if not k.startswith("_")
                }
            elif isinstance(wf_item, dict):
                wf = wf_item
            else:
                continue

            wf_func = str(wf.get("function", "")).strip().upper()
            if not wf_func:
                continue

            # Arguments
            wf_args = wf.get("arguments", [])
            if wf_args == ["*"]:
                args_str = "*"
            elif wf_args:
                formatted_args = []
                for a in wf_args:
                    if isinstance(a, str):
                        _, _, qa = self._resolve_column_ref(a, clean_base_table)
                        formatted_args.append(qa)
                    else:
                        formatted_args.append(str(a))
                args_str = ", ".join(formatted_args)
            elif wf_func == "COUNT":
                args_str = "*"
            else:
                args_str = ""

            # Partition By
            wf_parts = wf.get("partition_by", [])
            if wf_parts:
                quoted_parts = []
                for p in wf_parts:
                    _, _, qp = self._resolve_column_ref(p, clean_base_table)
                    quoted_parts.append(qp)
                part_clause = f"PARTITION BY {', '.join(quoted_parts)}"
            else:
                part_clause = ""

            # Order By
            wf_orders = wf.get("order_by", [])
            if wf_orders:
                quoted_orders = []
                for raw_ord in wf_orders:
                    if hasattr(raw_ord, "__dict__"):
                        ord_item = {k: v for k, v in raw_ord.__dict__.items()}
                    else:
                        ord_item = raw_ord
                    col_ref = ord_item.get("column")
                    if not col_ref:
                        continue
                    direction = ord_item.get("direction", "ASC").upper()
                    if direction not in ("ASC", "DESC"):
                        direction = "ASC"
                    prefix = (
                        ord_item.get("table_prefix")
                        or ord_item.get("tablePrefix")
                        or clean_base_table
                    )
                    _, _, qo = self._resolve_column_ref(col_ref, prefix)
                    quoted_orders.append(f"{qo} {direction}")
                order_clause = (
                    f"ORDER BY {', '.join(quoted_orders)}" if quoted_orders else ""
                )
            else:
                order_clause = ""

            # Frame
            wf_frame = wf.get("frame")
            if wf_frame:
                if hasattr(wf_frame, "__dict__"):
                    wf_frame = {k: v for k, v in wf_frame.__dict__.items()}
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
            else:
                frame_clause = ""

            over_tokens = [
                tok for tok in (part_clause, order_clause, frame_clause) if tok
            ]
            over_clause = f"OVER ({' '.join(over_tokens)})"
            wf_expr = f"{wf_func}({args_str}) {over_clause}"

            alias = wf.get("alias")
            if alias:
                self.select_clause_items.append(
                    f"{wf_expr} AS {self.dialect.quote_alias(alias)}"
                )
                self.select_column_names.append(alias)
            else:
                self.select_clause_items.append(wf_expr)
                self.select_column_names.append(wf_func)

        # 4. Process Filters
        filters_spec = self.spec.get("filters", [])
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
        for raw_flt in filters_spec:
            if hasattr(raw_flt, "__dict__"):
                flt = {k: v for k, v in raw_flt.__dict__.items()}
            else:
                flt = raw_flt
            is_enforced = flt.get("_enforced") is True
            params_start = len(self.params)

            op = str(flt.get("op", flt.get("operator", "eq"))).strip().lower()
            val = flt.get("value")
            subquery = flt.get("subquery")
            col_ref = flt.get("column")

            is_subquery_filter = (
                subquery is not None
                or (isinstance(val, dict) and "table" in val)
                or (hasattr(val, "__dict__") and hasattr(val, "table"))
            )

            if not col_ref and op not in ("exists", "not_exists", "not exists"):
                continue

            if col_ref:
                prefix = (
                    flt.get("tablePrefix")
                    or flt.get("table_prefix")
                    or flt.get("table")
                    or clean_base_table
                )
                _, _, quoted_ref = self._resolve_column_ref(col_ref, prefix)
            else:
                quoted_ref = ""

            clause_str = ""

            if op in ("exists", "not_exists", "not exists"):
                if not is_subquery_filter:
                    raise CompilationError("EXISTS filter requires a nested subquery.")
                sub_spec = subquery if subquery is not None else val
                sub_dict = sub_spec if isinstance(sub_spec, dict) else sub_spec.__dict__
                sub_compiler = QueryCompiler(
                    sub_dict,
                    schema=self.schema,
                    dialect=self.dialect,
                    middleware=None,
                    allow_unknown_keys=True,
                    inner=True,
                )
                sub_sql, sub_params, _, _ = sub_compiler.compile()
                not_pfx = "NOT " if "not" in op else ""
                clause_str = f"{not_pfx}EXISTS ({sub_sql})"
                self.params.extend(sub_params)

            elif (
                val is None
                and not is_subquery_filter
                and op in ("eq", "=", "neq", "!=")
            ):
                if op in ("eq", "="):
                    clause_str = f"{quoted_ref} IS NULL"
                else:
                    clause_str = f"{quoted_ref} IS NOT NULL"

            elif op in ("is_null", "is null"):
                clause_str = f"{quoted_ref} IS NULL"
            elif op in ("is_not_null", "is not null"):
                clause_str = f"{quoted_ref} IS NOT NULL"

            elif is_subquery_filter and op in ("in", "not in", "not_in"):
                sub_spec = subquery if subquery is not None else val
                sub_dict = sub_spec if isinstance(sub_spec, dict) else sub_spec.__dict__
                sub_compiler = QueryCompiler(
                    sub_dict,
                    schema=self.schema,
                    dialect=self.dialect,
                    middleware=None,
                    allow_unknown_keys=True,
                    inner=True,
                )
                sub_sql, sub_params, _, _ = sub_compiler.compile()
                not_pfx = "NOT " if "not" in op else ""
                clause_str = f"{quoted_ref} {not_pfx}IN ({sub_sql})"
                self.params.extend(sub_params)

            elif is_subquery_filter and op in OPERATOR_MAP:
                sub_spec = subquery if subquery is not None else val
                sub_dict = sub_spec if isinstance(sub_spec, dict) else sub_spec.__dict__
                sub_compiler = QueryCompiler(
                    sub_dict,
                    schema=self.schema,
                    dialect=self.dialect,
                    middleware=None,
                    allow_unknown_keys=True,
                    inner=True,
                )
                sub_sql, sub_params, _, _ = sub_compiler.compile()
                sql_op = OPERATOR_MAP[op]
                clause_str = f"{quoted_ref} {sql_op} ({sub_sql})"
                self.params.extend(sub_params)

            elif op in OPERATOR_MAP:
                sql_op = OPERATOR_MAP[op]
                clause_str = f"{quoted_ref} {sql_op} {self.dialect.placeholder}"
                self.params.append(val)

            elif op in ("contains", "not_contains", "not contains"):
                expr = self.dialect.format_substring_match(quoted_ref)
                if "not" in op:
                    clause_str = f"NOT ({expr})"
                else:
                    clause_str = expr
                self.params.append(f"%{self.dialect.escape_like(val)}%")

            elif op in (
                "starts_with",
                "startswith",
                "not_starts_with",
                "not startswith",
            ):
                expr = self.dialect.format_substring_match(quoted_ref)
                if "not" in op:
                    clause_str = f"NOT ({expr})"
                else:
                    clause_str = expr
                self.params.append(f"{self.dialect.escape_like(val)}%")

            elif op in ("ends_with", "endswith", "not_ends_with", "not endswith"):
                expr = self.dialect.format_substring_match(quoted_ref)
                if "not" in op:
                    clause_str = f"NOT ({expr})"
                else:
                    clause_str = expr
                self.params.append(f"%{self.dialect.escape_like(val)}")

            elif op in ("like", "not_like", "not like"):
                if "not" in op:
                    clause_str = f"{quoted_ref} NOT LIKE {self.dialect.placeholder}"
                else:
                    clause_str = self.dialect.format_like(quoted_ref)
                self.params.append(f"{val}")

            elif op in ("ilike", "not_ilike", "not ilike"):
                if "not" in op:
                    clause_str = f"NOT ({self.dialect.format_ilike(quoted_ref)})"
                else:
                    clause_str = self.dialect.format_ilike(quoted_ref)
                self.params.append(f"{val}")

            elif op in ("in", "not in", "not_in"):
                if isinstance(val, (list, tuple, set)):
                    val_list = list(val)
                elif isinstance(val, str):
                    val_list = [v.strip() for v in val.split(",") if v.strip()]
                else:
                    val_list = [val]

                if len(val_list) == 0:
                    if "not" in op:
                        clause_str = "1 = 1"
                    else:
                        clause_str = "1 = 0"
                elif len(val_list) > MAX_IN_VALUES:
                    raise CompilationError(
                        f"IN clause value count ({len(val_list)}) exceeds maximum limit of {MAX_IN_VALUES}."
                    )
                elif "not" in op:
                    non_null_vals = [v for v in val_list if v is not None]
                    if not non_null_vals:
                        clause_str = "1 = 0"
                    else:
                        placeholders = ", ".join(
                            [self.dialect.placeholder] * len(non_null_vals)
                        )
                        clause_str = f"({quoted_ref} NOT IN ({placeholders}) AND {quoted_ref} IS NOT NULL)"
                        self.params.extend(non_null_vals)
                else:
                    has_none = any(v is None for v in val_list)
                    non_null_vals = [v for v in val_list if v is not None]
                    if has_none and non_null_vals:
                        placeholders = ", ".join(
                            [self.dialect.placeholder] * len(non_null_vals)
                        )
                        clause_str = f"({quoted_ref} IN ({placeholders}) OR {quoted_ref} IS NULL)"
                        self.params.extend(non_null_vals)
                    elif has_none and not non_null_vals:
                        clause_str = f"{quoted_ref} IS NULL"
                    else:
                        placeholders = ", ".join(
                            [self.dialect.placeholder] * len(val_list)
                        )
                        clause_str = f"{quoted_ref} IN ({placeholders})"
                        self.params.extend(val_list)

            elif op in ("between", "not_between", "not between"):
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    p0, p1 = val[0], val[1]
                elif isinstance(val, str) and " AND " in val:
                    p0, p1 = val.split(" AND ", 1)
                    p0, p1 = p0.strip(), p1.strip()
                elif isinstance(val, str) and "," in val:
                    p0, p1 = val.split(",", 1)
                    p0, p1 = p0.strip(), p1.strip()
                else:
                    raise CompilationError("BETWEEN filter requires exactly 2 bounds.")
                not_pfx = "NOT " if "not" in op else ""
                clause_str = f"{quoted_ref} {not_pfx}BETWEEN {self.dialect.placeholder} AND {self.dialect.placeholder}"
                self.params.extend([p0, p1])

            elif op in _CUSTOM_FILTER_OPERATORS:
                handler = _CUSTOM_FILTER_OPERATORS[op]
                res = handler(quoted_ref, val, self.dialect)
                if isinstance(res, tuple):
                    clause_str, new_params = res
                    if isinstance(new_params, (list, tuple)):
                        self.params.extend(new_params)
                    else:
                        self.params.append(new_params)
                elif isinstance(res, str):
                    clause_str = res
                else:
                    raise CompilationError(
                        f"Custom filter operator '{op}' returned invalid result: {type(res).__name__}"
                    )
            else:
                raise CompilationError(f"Unsupported filter operator: '{op}'")

            seg = self.params[params_start:]
            del self.params[params_start:]
            if is_enforced:
                enforced_clauses.append(clause_str)
                enforced_params.extend(seg)
                continue
            client_params.extend(seg)

            comb = flt.get("combiner") or filter_join
            comb = comb.strip().upper() if isinstance(comb, str) else filter_join
            if comb not in ("AND", "OR"):
                comb = filter_join

            open_p = ""
            p_open = flt.get("parenOpen")
            if p_open:
                if isinstance(p_open, bool):
                    n_open = 1
                elif isinstance(p_open, int):
                    n_open = max(p_open, 0)
                else:
                    n_open = str(p_open).count("(") or 1
                n_open = min(n_open, 16)
                open_p = "(" * n_open
                paren_depth += n_open

            close_p = ""
            p_close = flt.get("parenClose")
            if p_close:
                if isinstance(p_close, bool):
                    n_close = 1
                elif isinstance(p_close, int):
                    n_close = max(p_close, 0)
                else:
                    n_close = str(p_close).count(")") or 1
                # Never close more groups than are open: an unbalanced ')' would
                # terminate the wrapping client group and let a trailing OR
                # escape the enforced (tenant/RLS) predicates.
                n_close = min(n_close, paren_depth)
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
            combined_filters = f"({' '.join(client_filter_tokens)})"
            self.where_clauses.append(combined_filters)
            self.params.extend(client_params)

        # 5. Process Having
        having_spec = self.spec.get("having", [])
        for raw_hvg in having_spec:
            if hasattr(raw_hvg, "__dict__"):
                hvg = {k: v for k, v in raw_hvg.__dict__.items()}
            else:
                hvg = raw_hvg

            col_ref = hvg.get("column")
            agg = str(hvg.get("agg", hvg.get("aggregate", "count"))).lower()
            op = str(hvg.get("op", hvg.get("operator", "gt"))).lower()
            val = hvg.get("value")

            if col_ref == "*":
                if agg == "count":
                    agg_expr = "COUNT(*)"
                else:
                    raise CompilationError(
                        f"Aggregate '{agg}' cannot be applied to '*' in HAVING."
                    )
            else:
                _, _, quoted_ref = self._resolve_column_ref(col_ref, clean_base_table)
                if agg in AGGREGATE_MAP:
                    agg_expr = self._aggregate_template(agg).format(quoted_ref)
                else:
                    continue

            if op not in OPERATOR_MAP:
                continue
            sql_op = OPERATOR_MAP[op]
            self.having_clauses.append(
                f"{agg_expr} {sql_op} {self.dialect.placeholder}"
            )
            self.params.append(val)

        # 6. Process Order By
        order_spec = self.spec.get("order_by", [])
        for raw_ord in order_spec:
            if hasattr(raw_ord, "__dict__"):
                ord_item = {k: v for k, v in raw_ord.__dict__.items()}
            else:
                ord_item = raw_ord

            col_ref = ord_item.get("column")
            if not col_ref:
                continue
            direction = ord_item.get("direction", "ASC").upper()
            if direction not in ("ASC", "DESC"):
                direction = "ASC"

            prefix = (
                ord_item.get("tablePrefix")
                or ord_item.get("table_prefix")
                or ord_item.get("table")
                or clean_base_table
            )
            _, _, quoted_ref = self._resolve_column_ref(col_ref, prefix)
            self.order_by_items.append(f"{quoted_ref} {direction}")

        # 7. Assemble SQL Query Parts
        is_distinct = self.spec.get("distinct", False) and not self.has_aggregation
        distinct_prefix = "DISTINCT " if is_distinct else ""

        select_str = f"{distinct_prefix}{', '.join(self.select_clause_items)}"
        joins_str = " ".join(self.join_clauses) if self.join_clauses else ""
        where_str = (
            f"WHERE {' AND '.join(self.where_clauses)}" if self.where_clauses else ""
        )

        group_by_str = ""
        has_grouping = bool(
            self.has_aggregation
            or self.spec.get("grouping_type")
            or self.spec.get("grouping_sets")
            or self.spec.get("rollup")
            or self.spec.get("cube")
        )
        if has_grouping and (
            self.group_by_items
            or self.spec.get("rollup")
            or self.spec.get("cube")
            or self.spec.get("grouping_sets")
            or self.spec.get("grouping_type")
        ):
            g_type = (self.spec.get("grouping_type") or "").lower()
            if g_type == "rollup" or self.spec.get("rollup"):
                rollup_spec = self.spec.get("rollup")
                r_cols = getattr(rollup_spec, "columns", None) if rollup_spec else None
                if r_cols is None and isinstance(rollup_spec, dict):
                    r_cols = rollup_spec.get("columns")
                if r_cols:
                    quoted_r = [
                        self._resolve_column_ref(c, clean_base_table)[2] for c in r_cols
                    ]
                    group_by_str = f"GROUP BY ROLLUP({', '.join(quoted_r)})"
                elif self.group_by_items:
                    group_by_str = f"GROUP BY ROLLUP({', '.join(self.group_by_items)})"
            elif g_type == "cube" or self.spec.get("cube"):
                cube_spec = self.spec.get("cube")
                c_cols = getattr(cube_spec, "columns", None) if cube_spec else None
                if c_cols is None and isinstance(cube_spec, dict):
                    c_cols = cube_spec.get("columns")
                if c_cols:
                    quoted_c = [
                        self._resolve_column_ref(c, clean_base_table)[2] for c in c_cols
                    ]
                    group_by_str = f"GROUP BY CUBE({', '.join(quoted_c)})"
                elif self.group_by_items:
                    group_by_str = f"GROUP BY CUBE({', '.join(self.group_by_items)})"
            elif g_type == "grouping_sets" or self.spec.get("grouping_sets"):
                g_sets = self.spec.get("grouping_sets") or []
                if hasattr(g_sets, "sets"):
                    g_sets = g_sets.sets
                formatted_sets = []
                for s in g_sets:
                    quoted_s = [
                        self._resolve_column_ref(c, clean_base_table)[2] for c in s
                    ]
                    formatted_sets.append(f"({', '.join(quoted_s)})")
                if formatted_sets:
                    group_by_str = (
                        f"GROUP BY GROUPING SETS({', '.join(formatted_sets)})"
                    )
                elif self.group_by_items:
                    group_by_str = f"GROUP BY {', '.join(self.group_by_items)}"
            elif self.group_by_items:
                group_by_str = f"GROUP BY {', '.join(self.group_by_items)}"

        having_str = (
            f"HAVING {' AND '.join(self.having_clauses)}" if self.having_clauses else ""
        )

        self._count_params_end = len(self.params)
        if not self.order_by_items and self.has_vector_search:
            if self._vector_include_dist:
                order_by_str = f"ORDER BY {self.dialect.quote_alias('_distance')} ASC"
            else:
                order_by_str = f"ORDER BY {self.vector_distance_expr} ASC"
                self.params.append(self._vector_param_val)
        elif not self.order_by_items and self.has_hybrid_search:
            if self._hybrid_include_scores:
                order_by_str = f"ORDER BY {self.dialect.quote_alias('_score')} DESC"
            else:
                order_by_str = f"ORDER BY {self.hybrid_score_expr} DESC"
                self.params.append(self._hybrid_vector_param)
                if self._hybrid_text_quoted_refs:
                    self.params.append(self._hybrid_text_param)
        elif (
            getattr(self.dialect, "requires_order_by_for_pagination", False)
            and self._unpaginated_nested()
        ):
            # SQL Server rejects ORDER BY in a subquery/CTE unless TOP/OFFSET is
            # present, and an unpaginated nested query needs none.
            order_by_str = ""
        elif (
            getattr(self.dialect, "requires_order_by_for_pagination", False)
            and not self.order_by_items
        ):
            order_by_str = "ORDER BY (SELECT NULL)"
        else:
            order_by_str = (
                f"ORDER BY {', '.join(self.order_by_items)}"
                if self.order_by_items
                else ""
            )

        limit_val = int(self.spec.get("limit", 50))
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
            if "limit" not in self.spec:
                limit_val = top_k_val
            else:
                limit_val = min(limit_val, top_k_val)

        limit = min(limit_val, self.max_limit)
        raw_offset = self.spec.get("offset")
        offset = min(
            max(int(raw_offset) if raw_offset is not None else 0, 0), MAX_OFFSET
        )

        if self._unpaginated_nested():
            limit_offset_str, limit_params = "", []
        else:
            limit_offset_str, limit_params = self.dialect.format_limit_offset(
                limit, offset
            )

        if getattr(self.dialect, "pagination_placement", "suffix") == "prefix":
            select_pfx = (
                f"SELECT {limit_offset_str} " if limit_offset_str else "SELECT "
            )
            query_parts = [f"{select_pfx}{select_str}", from_str]
            if joins_str:
                query_parts.append(joins_str)
            if where_str:
                query_parts.append(where_str)
            if group_by_str:
                query_parts.append(group_by_str)
            if having_str:
                query_parts.append(having_str)
            if order_by_str:
                query_parts.append(order_by_str)
            main_sql = "\n".join(query_parts)
            main_params = limit_params + from_params + list(self.params)
        else:
            query_parts = [f"SELECT {select_str}", from_str]
            if joins_str:
                query_parts.append(joins_str)
            if where_str:
                query_parts.append(where_str)
            if group_by_str:
                query_parts.append(group_by_str)
            if having_str:
                query_parts.append(having_str)
            if order_by_str:
                query_parts.append(order_by_str)
            if limit_offset_str:
                query_parts.append(limit_offset_str)
            main_sql = "\n".join(query_parts)
            main_params = from_params + list(self.params) + limit_params

        # Count query construction
        count_query_parts = ["SELECT COUNT(*)", from_str]
        if joins_str:
            count_query_parts.append(joins_str)
        if where_str:
            count_query_parts.append(where_str)

        if group_by_str:
            # derived-table columns need a name (SQL Server error 8155)
            subquery_parts = ["SELECT 1 AS qb_one", from_str]
            if joins_str:
                subquery_parts.append(joins_str)
            if where_str:
                subquery_parts.append(where_str)
            subquery_parts.append(group_by_str)
            if having_str:
                subquery_parts.append(having_str)
            count_sql = (
                f"SELECT COUNT(*) FROM ({' '.join(subquery_parts)}) AS count_subquery"
            )
        else:
            count_sql = "\n".join(count_query_parts)

        count_params = from_params + list(
            self.params[self._count_skip_lead : self._count_params_end]
        )

        # Process CTEs (Common Table Expressions)
        ctes_spec = self.spec.get("ctes") or []
        cte_params: list[Any] = []
        cte_sql_prefix = ""
        if ctes_spec:
            has_recursive = any(
                (
                    c.get("recursive")
                    if isinstance(c, dict)
                    else getattr(c, "recursive", False)
                )
                for c in ctes_spec
            )
            with_kw = "WITH RECURSIVE " if has_recursive else "WITH "
            compiled_ctes: list[str] = []
            for cte in ctes_spec:
                if hasattr(cte, "__dict__"):
                    cte_dict = {
                        k: v for k, v in cte.__dict__.items() if not k.startswith("_")
                    }
                elif isinstance(cte, dict):
                    cte_dict = cte
                else:
                    raise CompilationError(
                        f"Invalid CTE item type: {type(cte).__name__}"
                    )
                c_name = cte_dict.get("name")
                c_cols = cte_dict.get("columns", [])
                c_mat = cte_dict.get("materialized")
                c_query = cte_dict.get("query")
                if isinstance(c_query, dict):
                    inner_query_spec = c_query
                elif hasattr(c_query, "__dict__"):
                    inner_query_spec = {
                        k: v
                        for k, v in c_query.__dict__.items()
                        if not k.startswith("_")
                    }
                else:
                    raise CompilationError(
                        f"CTE '{c_name}' query must be a QuerySpec or dict."
                    )

                inner_compiler = QueryCompiler(
                    inner_query_spec,
                    schema=self.schema,
                    dialect=self.dialect,
                    allow_unknown_keys=True,
                    inner=True,
                )
                inner_sql, inner_params, _, _ = inner_compiler.compile()
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
            cte_sql_prefix = f"{with_kw}{', '.join(compiled_ctes)}\n"
            main_sql = f"{cte_sql_prefix}{main_sql}"
            main_params = cte_params + main_params
            count_sql = f"{cte_sql_prefix}{count_sql}"
            count_params = cte_params + count_params

        # Process Set Operations (UNION, UNION ALL, INTERSECT, EXCEPT, MINUS)
        set_ops_spec = self.spec.get("set_operations") or []
        if set_ops_spec:
            for so in set_ops_spec:
                if hasattr(so, "__dict__"):
                    so_dict = {
                        k: v for k, v in so.__dict__.items() if not k.startswith("_")
                    }
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
                sub_compiler = QueryCompiler(
                    sub_query,
                    schema=self.schema,
                    dialect=self.dialect,
                    allow_unknown_keys=True,
                )
                sub_sql, sub_params, _, _ = sub_compiler.compile()
                main_sql = f"{main_sql}\n{op}\n{sub_sql}"
                main_params = main_params + sub_params
            count_sql = f"SELECT COUNT(*) FROM (\n{main_sql}\n) AS set_op_count"
            count_params = list(main_params)

        if self.middleware is not None:
            compilation = {
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


AnalyticalCompiler = QueryCompiler
