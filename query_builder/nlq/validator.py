"""
AST Schema Grounder & Safety Validator for Natural Language to Visual Query.
"""

from __future__ import annotations

from typing import Any

from query_builder.compiler import OPERATOR_MAP
from query_builder.models import FilterSpec, HavingSpec, JoinSpec, OrderBySpec, QuerySpec
from query_builder.nlq.models import NlqValidationError

VALID_JOIN_TYPES = {"INNER", "LEFT", "RIGHT", "FULL", "CROSS"}
VALID_AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "DISTINCT_COUNT"}
VALID_DIRECTIONS = {"ASC", "DESC"}


class NlqAstValidator:
    """Validates and grounds LLM-generated QuerySpec AST dictionaries against database schemas."""

    def __init__(self, schema: dict[str, Any] | None = None) -> None:
        self.schema = schema or {}
        self.tables_meta: dict[str, dict[str, Any]] = {}
        self._index_schema()

    def _index_schema(self) -> None:
        """Indexes schema tables and columns for case-insensitive lookup."""
        raw_tables = self.schema.get("tables", self.schema)
        if isinstance(raw_tables, dict):
            for t_name, t_meta in raw_tables.items():
                if isinstance(t_meta, dict):
                    self.tables_meta[t_name.lower()] = {
                        "original_name": t_name,
                        "columns": self._extract_column_names(t_meta.get("columns", {})),
                    }

    def _extract_column_names(self, cols: Any) -> set[str]:
        result: set[str] = set()
        if isinstance(cols, dict):
            for c_name in cols:
                result.add(str(c_name).lower())
        elif isinstance(cols, list):
            for c in cols:
                if isinstance(c, dict) and "name" in c:
                    result.add(str(c["name"]).lower())
                elif isinstance(c, str):
                    result.add(c.lower())
        return result

    def validate(self, raw_ast: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Validates, grounds, and sanitizes an AST dict, returning the sanitized dict and any warnings."""
        if not isinstance(raw_ast, dict):
            raise NlqValidationError(f"Expected dictionary AST, got {type(raw_ast).__name__}")

        warnings: list[str] = []

        # 1. Base table validation
        table = raw_ast.get("table")
        if not table or not isinstance(table, str) or not table.strip():
            raise NlqValidationError("QuerySpec AST must specify a non-empty 'table' string.")

        table_str = table.strip()
        matched_table = self._resolve_table(table_str)
        if matched_table:
            table_str = matched_table
        elif self.tables_meta:
            warnings.append(f"Table '{table_str}' was not found in the supplied database schema.")

        # 2. Columns validation
        raw_cols = raw_ast.get("columns", [])
        if not isinstance(raw_cols, list):
            raw_cols = []
            warnings.append("'columns' field was not a list; defaulted to empty column list.")

        sanitized_cols: list[str | dict[str, Any]] = []
        for col in raw_cols:
            if isinstance(col, str):
                col_name = col.strip()
                if col_name:
                    sanitized_cols.append(self._resolve_column(table_str, col_name))
            elif isinstance(col, dict):
                c_name = col.get("column", "")
                if not isinstance(c_name, str) or not c_name.strip():
                    continue
                agg = col.get("agg")
                if agg and str(agg).upper() in VALID_AGGREGATES:
                    agg = str(agg).upper()
                else:
                    agg = None
                alias = col.get("alias")
                sanitized_cols.append({
                    "column": self._resolve_column(table_str, c_name.strip()),
                    **({"agg": agg} if agg else {}),
                    **({"alias": str(alias).strip()} if alias else {}),
                })

        # 3. Joins validation
        raw_joins = raw_ast.get("joins", [])
        sanitized_joins: list[dict[str, Any]] = []
        if isinstance(raw_joins, list):
            for join_item in raw_joins:
                if not isinstance(join_item, dict):
                    continue
                j_table = join_item.get("table", "")
                if not isinstance(j_table, str) or not j_table.strip():
                    continue
                j_type = str(join_item.get("type", "INNER")).upper()
                if j_type not in VALID_JOIN_TYPES:
                    j_type = "INNER"
                resolved_j_table = self._resolve_table(j_table.strip()) or j_table.strip()
                left_table = join_item.get("left_table", table_str)
                left_col = join_item.get("left_col", "id")
                right_col = join_item.get("right_col", "id")
                sanitized_joins.append({
                    "table": resolved_j_table,
                    "type": j_type,
                    "left_table": left_table,
                    "left_col": left_col,
                    "right_col": right_col,
                })

        # 4. Filters validation
        raw_filters = raw_ast.get("filters", [])
        sanitized_filters: list[dict[str, Any]] = []
        if isinstance(raw_filters, list):
            for f in raw_filters:
                if not isinstance(f, dict):
                    continue
                col_name = f.get("column", "")
                if not isinstance(col_name, str) or not col_name.strip():
                    continue
                op = str(f.get("op", "=")).upper()
                if op not in OPERATOR_MAP and op not in {"=", "!=", ">", "<", ">=", "<=", "LIKE", "ILIKE", "IN", "NOT IN", "BETWEEN", "IS NULL", "IS NOT NULL"}:
                    op = "="
                val = f.get("value")
                sanitized_filters.append({
                    "column": col_name.strip(),
                    "op": op,
                    "value": val,
                    **({"tablePrefix": f["tablePrefix"]} if "tablePrefix" in f else {}),
                })

        filter_join = str(raw_ast.get("filter_join", "AND")).upper()
        if filter_join not in {"AND", "OR"}:
            filter_join = "AND"

        # 5. Having validation
        raw_having = raw_ast.get("having", [])
        sanitized_having: list[dict[str, Any]] = []
        if isinstance(raw_having, list):
            for h in raw_having:
                if isinstance(h, dict) and "column" in h:
                    sanitized_having.append({
                        "column": str(h["column"]).strip(),
                        "op": str(h.get("op", "=")).upper(),
                        "value": h.get("value"),
                    })

        # 6. Order by validation
        raw_order_by = raw_ast.get("order_by", [])
        sanitized_order_by: list[dict[str, Any]] = []
        if isinstance(raw_order_by, list):
            for ob in raw_order_by:
                if not isinstance(ob, dict):
                    continue
                col_name = ob.get("column", "")
                if not isinstance(col_name, str) or not col_name.strip():
                    continue
                direction = str(ob.get("direction", "ASC")).upper()
                if direction not in VALID_DIRECTIONS:
                    direction = "ASC"
                sanitized_order_by.append({
                    "column": col_name.strip(),
                    "direction": direction,
                    **({"tablePrefix": ob["tablePrefix"]} if "tablePrefix" in ob else {}),
                })

        # 7. Pagination and flags
        limit = raw_ast.get("limit", 50)
        try:
            limit = max(0, int(limit))
        except (ValueError, TypeError):
            limit = 50

        offset = raw_ast.get("offset", 0)
        try:
            offset = max(0, int(offset))
        except (ValueError, TypeError):
            offset = 0

        distinct = bool(raw_ast.get("distinct", False))

        # 8. Vector / Hybrid search
        vector_search = raw_ast.get("vector_search")
        if isinstance(vector_search, dict):
            v_col = vector_search.get("column", "embedding")
            v_vec = vector_search.get("vector", vector_search.get("query_vector"))
            if not isinstance(v_vec, (list, tuple)) or len(v_vec) == 0:
                vector_search = None
            else:
                metric = str(vector_search.get("metric", "cosine")).lower()
                if metric not in {"cosine", "euclidean", "l2", "dot_product", "inner_product"}:
                    metric = "cosine"
                vector_search = {
                    "vector": [float(x) for x in v_vec],
                    "column": str(v_col).strip() if v_col else "embedding",
                    "top_k": max(1, int(vector_search.get("top_k", 10))),
                    "metric": metric,
                }
        else:
            vector_search = None

        hybrid_search = raw_ast.get("hybrid_search")
        if isinstance(hybrid_search, dict):
            h_vec = hybrid_search.get("vector")
            if not isinstance(h_vec, (list, tuple)) or len(h_vec) == 0:
                hybrid_search = None
            else:
                hybrid_search = {
                    "vector": [float(x) for x in h_vec],
                    "vector_column": str(hybrid_search.get("vector_column", "embedding")),
                    "query_text": str(hybrid_search.get("query_text", "")),
                    "text_columns": list(hybrid_search.get("text_columns", [])),
                    "alpha": float(hybrid_search.get("alpha", 0.5)),
                    "fusion": str(hybrid_search.get("fusion", "rrf")),
                    "rrf_k": int(hybrid_search.get("rrf_k", 60)),
                    "top_k": max(1, int(hybrid_search.get("top_k", 10))),
                    "metric": str(hybrid_search.get("metric", "cosine")),
                }
        else:
            hybrid_search = None

        result_ast: dict[str, Any] = {
            "table": table_str,
            "columns": sanitized_cols,
            "joins": sanitized_joins,
            "filters": sanitized_filters,
            "filter_join": filter_join,
            "having": sanitized_having,
            "order_by": sanitized_order_by,
            "limit": limit,
            "offset": offset,
            "distinct": distinct,
            "vector_search": vector_search,
            "hybrid_search": hybrid_search,
        }

        # Verify QuerySpec instantiation
        try:
            QuerySpec(
                table=result_ast["table"],
                columns=result_ast["columns"],
                joins=[JoinSpec(**j) for j in result_ast["joins"]],
                filters=[FilterSpec(**f) for f in result_ast["filters"]],
                filter_join=result_ast["filter_join"],
                having=[HavingSpec(**h) for h in result_ast["having"]],
                order_by=[OrderBySpec(**o) for o in result_ast["order_by"]],
                limit=result_ast["limit"],
                offset=result_ast["offset"],
                distinct=result_ast["distinct"],
                vector_search=result_ast["vector_search"],
                hybrid_search=result_ast["hybrid_search"],
            )
        except Exception as exc:  # pragma: no cover - defensive validation
            raise NlqValidationError(f"Failed to instantiate QuerySpec from validated AST: {exc}") from exc

        return result_ast, warnings

    def _resolve_table(self, table_name: str) -> str | None:
        """Looks up table name in schema case-insensitively."""
        t_lower = table_name.lower()
        if t_lower in self.tables_meta:
            return str(self.tables_meta[t_lower]["original_name"])
        return None

    def _resolve_column(self, table_name: str, col_name: str) -> str:
        """Looks up column name in table schema case-insensitively if available."""
        t_lower = table_name.lower()
        if t_lower in self.tables_meta:
            cols = self.tables_meta[t_lower]["columns"]
            c_lower = col_name.lower()
            for original_c in cols:
                if original_c == c_lower:
                    return col_name
        return col_name
