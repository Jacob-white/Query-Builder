"""
Autonomous Self-Healing Query Engine.
=====================================
Analyzes AI-generated QuerySpec ASTs, detects anomalies (missing joins, fuzzy column typos,
unresolved tables, or safety violations), and autonomously repairs them using Dijkstra
relational pathfinding and schema alignment, or formats 1-shot repair prompts.
"""

from __future__ import annotations

import difflib
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.join_solver import find_best_join_condition, find_join_path


def _extract_table_and_column(ref: str, default_table: str) -> tuple[str, str]:
    """Extracts (table, column) from a string reference like 'users.id' or 'id'."""
    clean = (
        ref.strip().replace('"', "").replace("`", "").replace("[", "").replace("]", "")
    )
    if "." in clean:
        parts = clean.split(".", 1)
        return parts[0], parts[1]
    return default_table, clean


OPERATOR_SYNONYMS: dict[str, str] = {
    "=": "eq",
    "==": "eq",
    "equals": "eq",
    "is": "eq",
    "!=": "neq",
    "<>": "neq",
    "not equals": "neq",
    "not_equals": "neq",
    "is not": "neq",
    "like": "contains",
    "ilike": "contains",
    "not in": "not_in",
    "not-in": "not_in",
    "notin": "not_in",
    "starts with": "starts_with",
    "startswith": "starts_with",
    "ends with": "ends_with",
    "endswith": "ends_with",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "is null": "is_null",
    "isnull": "is_null",
    "is not null": "is_not_null",
    "isnotnull": "is_not_null",
}


class SelfHealingQueryEngine:
    """
    Self-healing engine ensuring AI-generated queries are valid, safe, and schema-compliant.
    """

    def __init__(self, schema: dict[str, Any] | None = None) -> None:
        self.schema = schema or {}

    def auto_heal(
        self,
        spec: dict[str, Any],
        dialect: str = "postgres",
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Autonomously inspects and heals an AI-generated query AST.

        Returns:
            Tuple of (healed_spec, healing_notes).
        """
        healed = dict(spec)
        notes: list[str] = []

        # 1. Operator Synonyms Normalization
        if "filters" in healed and isinstance(healed["filters"], list):
            new_filters: list[dict[str, Any]] = []
            for f in healed["filters"]:
                if isinstance(f, dict):
                    f_copy = dict(f)
                    op = str(f_copy.get("op", "")).lower().strip()
                    if op in OPERATOR_SYNONYMS:
                        canon_op = OPERATOR_SYNONYMS[op]
                        f_copy["op"] = canon_op
                        notes.append(
                            f"Operator synonym healed in filter: mapped '{op}' to '{canon_op}'."
                        )
                    new_filters.append(f_copy)
                else:
                    new_filters.append(f)
            healed["filters"] = new_filters

        if "having" in healed and isinstance(healed["having"], list):
            new_having: list[dict[str, Any]] = []
            for h in healed["having"]:
                if isinstance(h, dict):
                    h_copy = dict(h)
                    op = str(h_copy.get("op", "")).lower().strip()
                    if op in OPERATOR_SYNONYMS:
                        canon_op = OPERATOR_SYNONYMS[op]
                        h_copy["op"] = canon_op
                        notes.append(
                            f"Operator synonym healed in having: mapped '{op}' to '{canon_op}'."
                        )
                    new_having.append(h_copy)
                else:
                    new_having.append(h)
            healed["having"] = new_having

        # 2. Primary Table Validation & Inference
        primary_table = healed.get("table", "").strip()
        if not primary_table:
            # Try to infer primary table from projections or filters
            cols = healed.get("columns", [])
            for c in cols:
                ref = c.get("column", "") if isinstance(c, dict) else str(c)
                if "." in ref:
                    primary_table = ref.split(".", 1)[0]
                    notes.append(
                        f"Inferred primary table '{primary_table}' from projection '{ref}'."
                    )
                    break

            if not primary_table:
                filters = healed.get("filters", [])
                for f in filters:
                    col = f.get("column", "")
                    prefix = f.get("tablePrefix")
                    if prefix:
                        primary_table = prefix
                        notes.append(
                            f"Inferred primary table '{primary_table}' from filter prefix."
                        )
                        break
                    elif "." in col:
                        primary_table = col.split(".", 1)[0]
                        notes.append(
                            f"Inferred primary table '{primary_table}' from filter column '{col}'."
                        )
                        break

            if not primary_table:
                # Fallback to first schema table or 'default_table'
                schema_tables = (
                    list(self.schema.get("tables", self.schema).keys())
                    if isinstance(self.schema, dict)
                    else []
                )
                primary_table = schema_tables[0] if schema_tables else "data"
                notes.append(f"Assigned default primary table '{primary_table}'.")

        schema_tables_dict = (
            self.schema.get("tables", self.schema)
            if isinstance(self.schema, dict)
            else {}
        )

        if (
            primary_table
            and isinstance(schema_tables_dict, dict)
            and schema_tables_dict
            and primary_table not in schema_tables_dict
        ):
            close_tables = difflib.get_close_matches(
                primary_table, list(schema_tables_dict.keys()), n=1, cutoff=0.6
            )
            if close_tables:
                notes.append(
                    f"Primary table typo healed: mapped '{primary_table}' to '{close_tables[0]}'."
                )
                primary_table = close_tables[0]

        healed["table"] = primary_table

        # 3. Cross-Table Unprefixed Column Resolution
        if isinstance(schema_tables_dict, dict) and primary_table:
            primary_meta = schema_tables_dict.get(primary_table, {})
            primary_cols = set(self._get_column_names(primary_meta))

            def _resolve_unprefixed_col(col_name: str) -> str:
                if not col_name or "." in col_name or col_name == "*":
                    return col_name
                if primary_cols and col_name in primary_cols:
                    return col_name
                matching_tables: list[str] = []
                for tname, tmeta in schema_tables_dict.items():
                    if tname != primary_table:
                        tcols = self._get_column_names(tmeta)
                        if col_name in tcols:
                            matching_tables.append(tname)
                if len(matching_tables) == 1:
                    target_tbl = matching_tables[0]
                    notes.append(
                        f"Cross-table column resolved: mapped '{col_name}' to '{target_tbl}.{col_name}'."
                    )
                    return f"{target_tbl}.{col_name}"
                return col_name

            resolved_cols: list[dict[str, Any] | str] = []
            for c in healed.get("columns", []):
                if isinstance(c, dict):
                    col_val = c.get("column", "")
                    res_val = _resolve_unprefixed_col(col_val)
                    if res_val != col_val:
                        c_dict = dict(c)
                        c_dict["column"] = res_val
                        resolved_cols.append(c_dict)
                    else:
                        resolved_cols.append(c)
                elif isinstance(c, str):
                    resolved_cols.append(_resolve_unprefixed_col(c))
                else:
                    resolved_cols.append(c)
            healed["columns"] = resolved_cols

            for f in healed.get("filters", []):
                if isinstance(f, dict) and not f.get("tablePrefix"):
                    f["column"] = _resolve_unprefixed_col(f.get("column", ""))

            for h in healed.get("having", []):
                if isinstance(h, dict):
                    h["column"] = _resolve_unprefixed_col(h.get("column", ""))

            for o in healed.get("order_by", []):
                if isinstance(o, dict) and not o.get("tablePrefix"):
                    o["column"] = _resolve_unprefixed_col(o.get("column", ""))

        # 4. Collect All Referenced Tables
        active_tables: list[str] = [primary_table]
        joins = list(healed.get("joins", []))

        for j in joins:
            jt = j.get("table")
            if jt and jt not in active_tables:
                active_tables.append(jt)

        referenced_tables: set[str] = set()

        # Projections
        for c in healed.get("columns", []):
            ref = c.get("column", "") if isinstance(c, dict) else str(c)
            if ref != "*":
                tbl, _ = _extract_table_and_column(ref, primary_table)
                referenced_tables.add(tbl)

        # Filters
        for f in healed.get("filters", []):
            if isinstance(f, dict):
                col = f.get("column", "")
                prefix = f.get("tablePrefix") or f.get("table_prefix")
                if prefix:
                    referenced_tables.add(prefix)
                elif "." in col:
                    tbl, _ = _extract_table_and_column(col, primary_table)
                    referenced_tables.add(tbl)

        # Having
        for h in healed.get("having", []):
            if isinstance(h, dict):
                col = h.get("column", "")
                if "." in col:
                    tbl, _ = _extract_table_and_column(col, primary_table)
                    referenced_tables.add(tbl)

        # Order By
        for o in healed.get("order_by", []):
            if isinstance(o, dict):
                col = o.get("column", "")
                prefix = o.get("tablePrefix") or o.get("table_prefix")
                if prefix:
                    referenced_tables.add(prefix)
                elif "." in col:
                    tbl, _ = _extract_table_and_column(col, primary_table)
                    referenced_tables.add(tbl)

        # Window Functions
        for w in healed.get("window_functions", []):
            if isinstance(w, dict):
                for pc in w.get("partition_by", []):
                    pc_str = str(pc)
                    if "." in pc_str:
                        tbl, _ = _extract_table_and_column(pc_str, primary_table)
                        referenced_tables.add(tbl)

        # 5. Autonomous Join Synthesis via Dijkstra / BFS
        for target_table in referenced_tables:
            if target_table not in active_tables and target_table != primary_table:
                # Find shortest relational path
                path = find_join_path(
                    active_tables, target_table, schema_data=self.schema
                )
                if path:
                    for join_step in path:
                        if join_step["table"] not in active_tables:
                            joins.append(join_step)
                            active_tables.append(join_step["table"])
                            notes.append(
                                f"Autonomous join healing: added {join_step['type']} `{join_step['table']}` "
                                f"on {join_step['left_col']}={join_step['right_col']}."
                            )
                else:
                    # Direct condition fallback
                    fallback = find_best_join_condition(
                        primary_table, target_table, schema_data=self.schema
                    )
                    join_obj = {
                        "type": "LEFT JOIN",
                        "table": target_table,
                        "left_table": primary_table,
                        "left_col": fallback["left_col"],
                        "right_col": fallback["right_col"],
                    }
                    joins.append(join_obj)
                    active_tables.append(target_table)
                    notes.append(
                        f"Autonomous join synthesis: linked `{target_table}` to `{primary_table}` "
                        f"on {fallback['left_col']}={fallback['right_col']}."
                    )

        healed["joins"] = joins

        # 6. Fuzzy Column Healing across Projections, Filters, Having, OrderBy, Joins, and Window Functions
        if isinstance(schema_tables_dict, dict):
            # Columns
            new_columns: list[dict[str, Any] | str] = []
            for col_item in healed.get("columns", []):
                if isinstance(col_item, dict):
                    raw_col = col_item.get("column", "")
                    tbl, col_name = _extract_table_and_column(raw_col, primary_table)
                    table_meta = schema_tables_dict.get(tbl, {})
                    cols_list = self._get_column_names(table_meta)
                    c_dict = col_item
                    if (
                        cols_list
                        and col_name not in cols_list
                        and not col_item.get("raw_expression")
                    ):
                        match = difflib.get_close_matches(
                            col_name, cols_list, n=1, cutoff=0.7
                        )
                        if match:
                            fixed_col = match[0]
                            c_dict = dict(col_item)
                            c_dict["column"] = (
                                f"{tbl}.{fixed_col}" if "." in raw_col else fixed_col
                            )
                            notes.append(
                                f"Fuzzy column healed: corrected '{raw_col}' to '{fixed_col}'."
                            )
                    new_columns.append(c_dict)
                else:
                    col_str = str(col_item)
                    if col_str != "*":
                        tbl, col_name = _extract_table_and_column(
                            col_str, primary_table
                        )
                        table_meta = schema_tables_dict.get(tbl, {})
                        cols_list = self._get_column_names(table_meta)
                        if cols_list and col_name not in cols_list:
                            match = difflib.get_close_matches(
                                col_name, cols_list, n=1, cutoff=0.7
                            )
                            if match:
                                fixed_col = match[0]
                                fixed_str = (
                                    f"{tbl}.{fixed_col}"
                                    if "." in col_str
                                    else fixed_col
                                )
                                notes.append(
                                    f"Fuzzy column healed: corrected '{col_str}' to '{fixed_str}'."
                                )
                                new_columns.append(fixed_str)
                                continue
                    new_columns.append(col_str)
            healed["columns"] = new_columns

            # Filters
            for f in healed.get("filters", []):
                if isinstance(f, dict):
                    prefix = f.get("tablePrefix") or f.get("table_prefix")
                    if prefix and prefix not in schema_tables_dict:
                        close_p = difflib.get_close_matches(
                            prefix, list(schema_tables_dict.keys()), n=1, cutoff=0.6
                        )
                        if close_p:
                            notes.append(
                                f"Fuzzy filter table prefix healed: corrected '{prefix}' to '{close_p[0]}'."
                            )
                            if "tablePrefix" in f:
                                f["tablePrefix"] = close_p[0]
                            if "table_prefix" in f:
                                f["table_prefix"] = close_p[0]
                    raw_col = f.get("column", "")
                    if raw_col:
                        tbl, col_name = _extract_table_and_column(
                            raw_col,
                            f.get("tablePrefix")
                            or f.get("table_prefix")
                            or primary_table,
                        )
                        table_meta = schema_tables_dict.get(tbl, {})
                        cols_list = self._get_column_names(table_meta)
                        if cols_list and col_name not in cols_list:
                            match = difflib.get_close_matches(
                                col_name, cols_list, n=1, cutoff=0.7
                            )
                            if match:
                                fixed_col = match[0]
                                f["column"] = (
                                    f"{tbl}.{fixed_col}"
                                    if "." in raw_col
                                    else fixed_col
                                )
                                notes.append(
                                    f"Fuzzy column healed in filter: corrected '{raw_col}' to '{fixed_col}'."
                                )

            # Having
            for h in healed.get("having", []):
                if isinstance(h, dict):
                    raw_col = h.get("column", "")
                    if raw_col:
                        tbl, col_name = _extract_table_and_column(
                            raw_col, primary_table
                        )
                        table_meta = schema_tables_dict.get(tbl, {})
                        cols_list = self._get_column_names(table_meta)
                        if cols_list and col_name not in cols_list:
                            match = difflib.get_close_matches(
                                col_name, cols_list, n=1, cutoff=0.7
                            )
                            if match:
                                fixed_col = match[0]
                                h["column"] = (
                                    f"{tbl}.{fixed_col}"
                                    if "." in raw_col
                                    else fixed_col
                                )
                                notes.append(
                                    f"Fuzzy column healed in having: corrected '{raw_col}' to '{fixed_col}'."
                                )

            # Order by
            for o in healed.get("order_by", []):
                if isinstance(o, dict):
                    prefix = o.get("tablePrefix") or o.get("table_prefix")
                    if prefix and prefix not in schema_tables_dict:
                        close_p = difflib.get_close_matches(
                            prefix, list(schema_tables_dict.keys()), n=1, cutoff=0.6
                        )
                        if close_p:
                            notes.append(
                                f"Fuzzy order_by table prefix healed: corrected '{prefix}' to '{close_p[0]}'."
                            )
                            if "tablePrefix" in o:
                                o["tablePrefix"] = close_p[0]
                            if "table_prefix" in o:
                                o["table_prefix"] = close_p[0]
                    raw_col = o.get("column", "")
                    if raw_col:
                        tbl, col_name = _extract_table_and_column(
                            raw_col,
                            o.get("tablePrefix")
                            or o.get("table_prefix")
                            or primary_table,
                        )
                        table_meta = schema_tables_dict.get(tbl, {})
                        cols_list = self._get_column_names(table_meta)
                        if cols_list and col_name not in cols_list:
                            match = difflib.get_close_matches(
                                col_name, cols_list, n=1, cutoff=0.7
                            )
                            if match:
                                fixed_col = match[0]
                                o["column"] = (
                                    f"{tbl}.{fixed_col}"
                                    if "." in raw_col
                                    else fixed_col
                                )
                                notes.append(
                                    f"Fuzzy column healed in order_by: corrected '{raw_col}' to '{fixed_col}'."
                                )

            # Joins
            for j in healed.get("joins", []):
                if isinstance(j, dict):
                    j_tbl = j.get("table")
                    j_left_tbl = j.get("left_table") or primary_table
                    if j_tbl and j_tbl not in schema_tables_dict:
                        close_jt = difflib.get_close_matches(
                            j_tbl, list(schema_tables_dict.keys()), n=1, cutoff=0.6
                        )
                        if close_jt:
                            notes.append(
                                f"Fuzzy join table healed: corrected '{j_tbl}' to '{close_jt[0]}'."
                            )
                            j_tbl = close_jt[0]
                            j["table"] = j_tbl
                    if j_left_tbl and j_left_tbl not in schema_tables_dict:
                        close_lt = difflib.get_close_matches(
                            j_left_tbl, list(schema_tables_dict.keys()), n=1, cutoff=0.6
                        )
                        if close_lt:
                            notes.append(
                                f"Fuzzy join left table healed: corrected '{j_left_tbl}' to '{close_lt[0]}'."
                            )
                            j_left_tbl = close_lt[0]
                            j["left_table"] = j_left_tbl
                    left_col = j.get("left_col")
                    right_col = j.get("right_col")
                    if left_col and j_left_tbl in schema_tables_dict:
                        l_meta = schema_tables_dict.get(j_left_tbl, {})
                        l_cols = self._get_column_names(l_meta)
                        if l_cols and left_col not in l_cols:
                            match = difflib.get_close_matches(
                                left_col, l_cols, n=1, cutoff=0.7
                            )
                            if match:
                                j["left_col"] = match[0]
                                notes.append(
                                    f"Fuzzy join column healed: corrected '{left_col}' to '{match[0]}' on `{j_left_tbl}`."
                                )
                    if right_col and j_tbl in schema_tables_dict:
                        r_meta = schema_tables_dict.get(j_tbl, {})
                        r_cols = self._get_column_names(r_meta)
                        if r_cols and right_col not in r_cols:
                            match = difflib.get_close_matches(
                                right_col, r_cols, n=1, cutoff=0.7
                            )
                            if match:
                                j["right_col"] = match[0]
                                notes.append(
                                    f"Fuzzy join column healed: corrected '{right_col}' to '{match[0]}' on `{j_tbl}`."
                                )

            # Window Functions
            for w in healed.get("window_functions", []):
                if isinstance(w, dict):
                    part_cols = w.get("partition_by", [])
                    if isinstance(part_cols, list):
                        new_parts: list[str] = []
                        for pc in part_cols:
                            pc_str = str(pc)
                            tbl, col_name = _extract_table_and_column(
                                pc_str, primary_table
                            )
                            tmeta = schema_tables_dict.get(tbl, {})
                            tcols = self._get_column_names(tmeta)
                            if tcols and col_name not in tcols:
                                match = difflib.get_close_matches(
                                    col_name, tcols, n=1, cutoff=0.7
                                )
                                if match:
                                    fixed = (
                                        f"{tbl}.{match[0]}"
                                        if "." in pc_str
                                        else match[0]
                                    )
                                    notes.append(
                                        f"Fuzzy column healed in window partition: corrected '{pc_str}' to '{fixed}'."
                                    )
                                    new_parts.append(fixed)
                                    continue
                            new_parts.append(pc_str)
                        w["partition_by"] = new_parts

        # 5. AST Security & Semantic Cleanliness
        try:
            from query_builder.compiler import QueryCompiler

            sql_to_check = QueryCompiler(
                healed, schema=self.schema, dialect=dialect
            ).compile()[0]
            sec_res = validate_sql_ast(sql_to_check)
            if not sec_res.get("valid"):
                notes.append(
                    f"Security sanitizer alert: {'; '.join(sec_res.get('violations', []))}"
                )
        except Exception as exc:
            notes.append(f"Compiler pre-check notice: {exc}")

        # 6. Default Limits
        if not healed.get("limit"):
            healed["limit"] = 50

        return healed, notes

    def _get_column_names(self, table_meta: Any) -> list[str]:
        """Extracts list of column names from table metadata."""
        if not isinstance(table_meta, dict):
            return []
        cols = table_meta.get("columns", [])
        if isinstance(cols, dict):
            return list(cols.keys())
        elif isinstance(cols, list):
            result = []
            for c in cols:
                if isinstance(c, dict):
                    result.append(c.get("name", ""))
                elif isinstance(c, str):
                    result.append(c)
            return result
        return []

    def generate_repair_prompt(
        self,
        broken_spec: dict[str, Any],
        errors: list[str],
        original_prompt: str = "",
    ) -> str:
        """
        Formats a structured 1-shot repair prompt to send back to an AI model when a query
        requires LLM correction.
        """
        err_list = "\n".join(f"- {e}" for e in errors)
        return (
            "The query AST generated previously contains the following schema and syntax errors:\n"
            f"{err_list}\n\n"
            f'Original Intent: "{original_prompt}"\n\n'
            "Please return a corrected, schema-grounded JSON QuerySpec resolving all issues listed above. "
            "Output ONLY valid JSON."
        )
