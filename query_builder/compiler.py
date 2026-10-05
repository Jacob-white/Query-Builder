"""
Declarative Query Compiler for SQL Explorer & Query Builder.
============================================================
Compiles declarative JSON query specifications into safe, parameterized SQL
with multi-dialect support (PostgreSQL, Snowflake, MSSQL, SQLite, MySQL),
automatic identifier quoting, tenant isolation injection, join resolution,
derived GROUP BY, HAVING, ordering, and pagination.
"""

from __future__ import annotations

from typing import Any, Callable

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
}

ALLOWED_COLUMN_KEYS = {"column", "name", "agg", "aggregate", "alias", "table"}
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
            if raw_col is None:
                continue
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
        else:
            raise ValidationError(
                f"Invalid column specification item type: {type(col).__name__}"
            )

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
    ) -> None:
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

        self.table_aliases: dict[str, str] = {}
        self._alias_counter = 0
        self.params: list[Any] = []
        self.where_clauses: list[str] = []
        self.having_clauses: list[str] = []
        self.select_clause_items: list[str] = []
        self.select_column_names: list[str] = []
        self.group_by_items: list[str] = []
        self.order_by_items: list[str] = []
        self.join_clauses: list[str] = []

        self.has_aggregation = False
        self._ownership_alias_counter = AliasCounter()

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
        for join in joins_spec:
            if hasattr(join, "__dict__"):
                join = {k: v for k, v in join.__dict__.items() if not k.startswith("_")}

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
                for cond in on_spec:
                    if hasattr(cond, "__dict__"):
                        cond = {k: v for k, v in cond.__dict__.items()}
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

                if agg in AGGREGATE_MAP:
                    self.has_aggregation = True
                    agg_expr = AGGREGATE_MAP[agg].format(quoted_ref)
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

        # 4. Process Filters
        filters_spec = self.spec.get("filters", [])
        filter_join = self.spec.get("filter_join", "AND").upper()
        if filter_join not in ("AND", "OR"):
            filter_join = "AND"

        client_filter_tokens: list[str] = []
        for flt in filters_spec:
            if hasattr(flt, "__dict__"):
                flt = {k: v for k, v in flt.__dict__.items()}

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
                expr = self.dialect.format_ilike(quoted_ref)
                if "not" in op:
                    clause_str = f"NOT ({expr})"
                else:
                    clause_str = expr
                self.params.append(f"%{val}%")

            elif op in (
                "starts_with",
                "startswith",
                "not_starts_with",
                "not startswith",
            ):
                expr = self.dialect.format_ilike(quoted_ref)
                if "not" in op:
                    clause_str = f"NOT ({expr})"
                else:
                    clause_str = expr
                self.params.append(f"{val}%")

            elif op in ("ends_with", "endswith", "not_ends_with", "not endswith"):
                expr = self.dialect.format_ilike(quoted_ref)
                if "not" in op:
                    clause_str = f"NOT ({expr})"
                else:
                    clause_str = expr
                self.params.append(f"%{val}")

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

            comb = flt.get("combiner") or filter_join
            comb = comb.upper() if isinstance(comb, str) else filter_join
            if comb not in ("AND", "OR"):
                comb = filter_join

            open_p = ""
            p_open = flt.get("parenOpen")
            if p_open:
                if isinstance(p_open, bool):
                    open_p = "("
                elif isinstance(p_open, int):
                    open_p = "(" * p_open
                else:
                    s_open = str(p_open)
                    open_p = "(" * (s_open.count("(") or 1)

            close_p = ""
            p_close = flt.get("parenClose")
            if p_close:
                if isinstance(p_close, bool):
                    close_p = ")"
                elif isinstance(p_close, int):
                    close_p = ")" * p_close
                else:
                    s_close = str(p_close)
                    close_p = ")" * (s_close.count(")") or 1)

            token = f"{open_p}{clause_str}{close_p}"
            if client_filter_tokens:
                client_filter_tokens.append(f"{comb} {token}")
            else:
                client_filter_tokens.append(token)

        if client_filter_tokens:
            combined_filters = f"({' '.join(client_filter_tokens)})"
            self.where_clauses.append(combined_filters)

        # 5. Process Having
        having_spec = self.spec.get("having", [])
        for hvg in having_spec:
            if hasattr(hvg, "__dict__"):
                hvg = {k: v for k, v in hvg.__dict__.items()}

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
                    agg_expr = AGGREGATE_MAP[agg].format(quoted_ref)
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
        for ord_item in order_spec:
            if hasattr(ord_item, "__dict__"):
                ord_item = {k: v for k, v in ord_item.__dict__.items()}

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
        if self.has_aggregation and self.group_by_items:
            group_by_str = f"GROUP BY {', '.join(self.group_by_items)}"

        having_str = (
            f"HAVING {' AND '.join(self.having_clauses)}" if self.having_clauses else ""
        )

        if (
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

        limit = min(int(self.spec.get("limit", 50)), self.max_limit)
        offset = min(max(int(self.spec.get("offset", 0)), 0), MAX_OFFSET)

        limit_offset_str, limit_params = self.dialect.format_limit_offset(limit, offset)

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
            subquery_parts = ["SELECT 1", from_str]
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

        count_params = from_params + list(self.params)

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
