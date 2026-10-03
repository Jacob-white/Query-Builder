"""
Declarative Query Compiler for SQL Explorer & Query Builder.
============================================================
Compiles declarative JSON query specifications into safe, parameterized SQL
with multi-dialect support (PostgreSQL, Snowflake, MSSQL, SQLite, MySQL),
automatic identifier quoting, tenant isolation injection, join resolution,
derived GROUP BY, HAVING, ordering, and pagination.
"""

from __future__ import annotations

from typing import Any

from query_builder.dialects import BaseDialect, get_dialect
from query_builder.join_solver import find_best_join_condition
from query_builder.security import (
    AliasCounter,
    SecurityError,
    resolve_ownership_predicate,
)


class CompilationError(Exception):
    """Raised when query specification is invalid or violates query safety rules."""


MAX_OFFSET = 1_000_000

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
        dialect: str | BaseDialect = "postgres",
        ownership_paths: dict[str, list[list[tuple[str, str, str]]]] | None = None,
        max_limit: int = 100,
    ) -> None:
        if hasattr(spec, "__dict__"):
            # Dataclass or Pydantic model
            self.spec = {
                k: v for k, v in spec.__dict__.items() if not k.startswith("_")
            }
        elif isinstance(spec, dict):
            self.spec = spec
        else:
            raise CompilationError(f"Unsupported spec type: {type(spec)}")

        self.user_id = user_id
        self.force_user_filter = force_user_filter
        self.tenant_id = tenant_id
        self.dialect = (
            dialect if isinstance(dialect, BaseDialect) else get_dialect(dialect)
        )
        self.ownership_paths = ownership_paths or {}
        self.max_limit = max_limit

        self.schema = schema or {}
        self.tables_meta: dict[str, Any] = self.schema.get("tables", {})
        self.rel_meta: list[dict[str, Any]] = self.schema.get("relationships", [])
        self.foreign_keys: list[dict[str, Any]] = self.schema.get("foreign_keys", [])

        self.table_aliases: dict[str, str] = {}
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

    def _get_alias(self, table_name: str) -> str:
        """Returns or creates a stable short alias (e.g. t1, t2) for a given table."""
        clean = table_name.split(".")[-1]
        if clean not in self.table_aliases:
            alias = f"t{len(self.table_aliases) + 1}"
            self.table_aliases[clean] = alias
        return self.table_aliases[clean]

    def _resolve_column_ref(
        self, col_ref: str, default_table: str
    ) -> tuple[str, str, str]:
        """Resolves a column reference to (alias, col_name, quoted_column_ref)."""
        if "." in col_ref:
            parts = col_ref.split(".", 1)
            tbl = parts[0]
            col = parts[1]
        else:
            tbl = default_table
            col = col_ref

        alias = self._get_alias(tbl)
        quoted_ref = f"{self.dialect.quote_identifier(alias)}.{self.dialect.quote_identifier(col)}"
        return alias, col, quoted_ref

    def compile(self) -> tuple[str, list[Any], str, list[Any]]:
        """
        Compiles the query specification.
        Returns:
            Tuple: (main_sql, main_params, count_sql, count_params)
        """
        base_table = self.spec.get("table")
        if not base_table:
            raise CompilationError(
                "Missing required 'table' parameter in query specification."
            )

        clean_base_table = base_table.split(".")[-1]
        if self.tables_meta and clean_base_table not in self.tables_meta:
            raise CompilationError(
                f"Invalid or missing base table in schema: '{base_table}'"
            )

        base_alias = self._get_alias(clean_base_table)

        # 1. Base table user / tenant isolation
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
            tbl_info = self.tables_meta.get(clean_base_table, {})
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

        # 2. Process Joins
        joins_spec = self.spec.get("joins", [])
        for join in joins_spec:
            if hasattr(join, "__dict__"):
                join = {k: v for k, v in join.__dict__.items() if not k.startswith("_")}

            target_table = join.get("table")
            if not target_table:
                raise CompilationError("Missing join target 'table'.")

            clean_target_table = target_table.split(".")[-1]
            if self.tables_meta and clean_target_table not in self.tables_meta:
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
                        right_ref, clean_target_table
                    )
                    on_conditions.append(f"{quoted_left} = {quoted_right}")
            elif join.get("left_col") and join.get("right_col"):
                left_tbl = join.get("left_table", clean_base_table)
                _, _, quoted_left = self._resolve_column_ref(join["left_col"], left_tbl)
                _, _, quoted_right = self._resolve_column_ref(
                    join["right_col"], clean_target_table
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
                        src_alias = self._get_alias(src)
                        tgt_alias = self._get_alias(tgt)
                        q_src = f"{self.dialect.quote_identifier(src_alias)}.{self.dialect.quote_identifier(rel['source_column'])}"
                        q_tgt = f"{self.dialect.quote_identifier(tgt_alias)}.{self.dialect.quote_identifier(rel['target_column'])}"
                        on_conditions.append(f"{q_src} = {q_tgt}")
                        found_rel = True
                        break

                if not found_rel and self.schema:
                    cond = find_best_join_condition(
                        clean_base_table, clean_target_table, self.schema
                    )
                    if cond:
                        l_alias = self._get_alias(cond["left_table"])
                        r_alias = self._get_alias(cond["right_table"])
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
                f"{join_type} {self.dialect.quote_identifier(clean_target_table)} {self.dialect.quote_identifier(target_alias)} ON {on_clause_str}"
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
            if clean_base_table in self.tables_meta:
                base_meta = self.tables_meta[clean_base_table]
                columns_spec = [
                    f"{clean_base_table}.{c['name']}"
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
                self.select_clause_items.append(
                    f"{quoted_ref} AS {self.dialect.quote_alias(col_item)}"
                )
                self.select_column_names.append(col_item)
                self.group_by_items.append(quoted_ref)
            elif isinstance(col_item, dict):
                raw_col_ref = col_item.get("column", col_item.get("name"))
                if not raw_col_ref or not isinstance(raw_col_ref, str):
                    continue
                agg = (col_item.get("agg") or col_item.get("aggregate") or "").lower()
                alias = col_item.get("alias")
                tbl = col_item.get("table", clean_base_table)
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

        client_filter_clauses = []
        for flt in filters_spec:
            if hasattr(flt, "__dict__"):
                flt = {k: v for k, v in flt.__dict__.items()}

            col_ref = flt.get("column")
            if not col_ref:
                continue

            op = flt.get("op", flt.get("operator", "eq")).lower()
            val = flt.get("value")
            prefix = flt.get("tablePrefix", flt.get("table", clean_base_table))

            _, _, quoted_ref = self._resolve_column_ref(col_ref, prefix)

            if op in ("is_null", "is null"):
                client_filter_clauses.append(f"{quoted_ref} IS NULL")
            elif op in ("is_not_null", "is not null"):
                client_filter_clauses.append(f"{quoted_ref} IS NOT NULL")
            elif op in OPERATOR_MAP:
                sql_op = OPERATOR_MAP[op]
                client_filter_clauses.append(
                    f"{quoted_ref} {sql_op} {self.dialect.placeholder}"
                )
                self.params.append(val)
            elif op in ("contains", "contains"):
                client_filter_clauses.append(self.dialect.format_ilike(quoted_ref))
                self.params.append(f"%{val}%")
            elif op in ("starts_with", "startswith"):
                client_filter_clauses.append(self.dialect.format_ilike(quoted_ref))
                self.params.append(f"{val}%")
            elif op in ("ends_with", "endswith"):
                client_filter_clauses.append(self.dialect.format_ilike(quoted_ref))
                self.params.append(f"%{val}")
            elif op in ("like",):
                client_filter_clauses.append(self.dialect.format_like(quoted_ref))
                self.params.append(f"{val}")
            elif op in ("ilike",):
                client_filter_clauses.append(self.dialect.format_ilike(quoted_ref))
                self.params.append(f"{val}")
            elif op in ("in", "not in", "not_in"):
                not_prefix = "NOT " if "not" in op else ""
                if isinstance(val, (list, tuple, set)):
                    val_list = list(val)
                elif isinstance(val, str):
                    val_list = [v.strip() for v in val.split(",") if v.strip()]
                else:
                    val_list = [val]

                placeholders = ", ".join([self.dialect.placeholder] * len(val_list))
                client_filter_clauses.append(
                    f"{quoted_ref} {not_prefix}IN ({placeholders})"
                )
                self.params.extend(val_list)
            elif op == "between":
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
                client_filter_clauses.append(
                    f"{quoted_ref} BETWEEN {self.dialect.placeholder} AND {self.dialect.placeholder}"
                )
                self.params.extend([p0, p1])
            else:
                raise CompilationError(f"Unsupported filter operator: '{op}'")

        if client_filter_clauses:
            combined_filters = f"({f' {filter_join} '.join(client_filter_clauses)})"
            self.where_clauses.append(combined_filters)

        # 5. Process Having
        having_spec = self.spec.get("having", [])
        for hvg in having_spec:
            if hasattr(hvg, "__dict__"):
                hvg = {k: v for k, v in hvg.__dict__.items()}

            col_ref = hvg.get("column")
            agg = hvg.get("agg", "count").lower()
            op = hvg.get("op", "gt").lower()
            val = hvg.get("value")

            _, _, quoted_ref = self._resolve_column_ref(col_ref, clean_base_table)
            if agg in AGGREGATE_MAP and op in OPERATOR_MAP:
                agg_expr = AGGREGATE_MAP[agg].format(quoted_ref)
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

            _, _, quoted_ref = self._resolve_column_ref(col_ref, clean_base_table)
            self.order_by_items.append(f"{quoted_ref} {direction}")

        # 7. Assemble SQL Query Parts
        is_distinct = self.spec.get("distinct", False) and not self.has_aggregation
        distinct_prefix = "DISTINCT " if is_distinct else ""

        select_str = f"{distinct_prefix}{', '.join(self.select_clause_items)}"
        from_str = f"FROM {self.dialect.quote_identifier(clean_base_table)} {self.dialect.quote_identifier(base_alias)}"
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
        order_by_str = (
            f"ORDER BY {', '.join(self.order_by_items)}" if self.order_by_items else ""
        )

        limit = min(int(self.spec.get("limit", 50)), self.max_limit)
        offset = min(max(int(self.spec.get("offset", 0)), 0), MAX_OFFSET)

        limit_offset_str, limit_params = self.dialect.format_limit_offset(limit, offset)

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

        query_parts.append(limit_offset_str)
        main_sql = "\n".join(query_parts)
        main_params = list(self.params) + limit_params

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

        return main_sql, main_params, count_sql, list(self.params)
