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

        # 1. Primary Table Validation & Inference
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

        healed["table"] = primary_table

        # 2. Collect All Referenced Tables
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
            col = f.get("column", "")
            prefix = f.get("tablePrefix")
            if prefix:
                referenced_tables.add(prefix)
            elif "." in col:
                tbl, _ = _extract_table_and_column(col, primary_table)
                referenced_tables.add(tbl)

        # Order By
        for o in healed.get("order_by", []):
            col = o.get("column", "")
            prefix = o.get("tablePrefix")
            if prefix:
                referenced_tables.add(prefix)
            elif "." in col:
                tbl, _ = _extract_table_and_column(col, primary_table)
                referenced_tables.add(tbl)

        # 3. Autonomous Join Synthesis via Dijkstra / BFS
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

        # 4. Fuzzy Column Healing against Schema
        schema_tables = (
            self.schema.get("tables", self.schema)
            if isinstance(self.schema, dict)
            else {}
        )
        if isinstance(schema_tables, dict):
            new_columns = []
            for col_item in healed.get("columns", []):
                if isinstance(col_item, dict):
                    raw_col = col_item.get("column", "")
                    tbl, col_name = _extract_table_and_column(raw_col, primary_table)
                    table_meta = schema_tables.get(tbl, {})
                    cols_list = self._get_column_names(table_meta)
                    c = col_item
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
                            c = dict(col_item)
                            c["column"] = (
                                f"{tbl}.{fixed_col}" if "." in raw_col else fixed_col
                            )
                            notes.append(
                                f"Fuzzy column healed: corrected '{raw_col}' to '{fixed_col}'."
                            )
                    new_columns.append(c)
                else:
                    col_str = str(col_item)
                    if col_str != "*":
                        tbl, col_name = _extract_table_and_column(
                            col_str, primary_table
                        )
                        table_meta = schema_tables.get(tbl, {})
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
