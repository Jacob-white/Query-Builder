"""
Prompt construction, schema serialization, and few-shot exemplars for NLQ engine.
"""

from __future__ import annotations

import json
from typing import Any


def serialize_schema_for_prompt(schema: dict[str, Any] | None) -> str:
    """Serializes a database schema dictionary into a concise markdown text for LLM prompts."""
    if not schema:
        return "Schema: No explicit schema provided. Infer plausible table and column identifiers from prompt."

    lines: list[str] = ["Database Schema:"]
    tables = schema.get("tables", schema)

    if isinstance(tables, dict):
        for tbl_name, tbl_data in tables.items():
            if not isinstance(tbl_data, dict):
                continue
            cols_info: list[str] = []
            columns = tbl_data.get("columns", {})
            if isinstance(columns, dict):
                for col_name, col_meta in columns.items():
                    if isinstance(col_meta, dict):
                        col_type = col_meta.get(
                            "data_type", col_meta.get("type", "TEXT")
                        )
                        pk = " (PK)" if col_meta.get("primary_key") else ""
                        cols_info.append(f"{col_name}: {col_type}{pk}")
                    else:
                        cols_info.append(f"{col_name}: {col_meta}")
            elif isinstance(columns, list):
                for col in columns:
                    if isinstance(col, dict):
                        cname = col.get("name", "unknown")
                        ctype = col.get("data_type", col.get("type", "TEXT"))
                        pk = " (PK)" if col.get("primary_key") else ""
                        cols_info.append(f"{cname}: {ctype}{pk}")
                    elif isinstance(col, str):
                        cols_info.append(col)

            fks_info: list[str] = []
            fks = tbl_data.get("foreign_keys", [])
            if isinstance(fks, list):
                for fk in fks:
                    if isinstance(fk, dict):
                        from_col = fk.get("column", fk.get("from_column", ""))
                        to_tbl = fk.get("target_table", fk.get("to_table", ""))
                        to_col = fk.get("target_column", fk.get("to_column", ""))
                        if from_col and to_tbl:
                            fks_info.append(f"{from_col} -> {to_tbl}.{to_col or 'id'}")

            col_str = ", ".join(cols_info) if cols_info else "no columns listed"
            fk_str = f" | FK: {', '.join(fks_info)}" if fks_info else ""
            lines.append(f"- Table `{tbl_name}`: [{col_str}]{fk_str}")

    return "\n".join(lines)


def get_few_shot_exemplars() -> list[dict[str, Any]]:
    """Returns curated few-shot exemplars mapping natural language to QuerySpec AST."""
    return [
        {
            "prompt": "Show top 10 customers sorted by balance descending",
            "spec": {
                "table": "customers",
                "columns": ["id", "name", "balance"],
                "joins": [],
                "filters": [],
                "filter_join": "AND",
                "having": [],
                "order_by": [{"column": "balance", "direction": "DESC"}],
                "limit": 10,
                "offset": 0,
                "distinct": False,
            },
        },
        {
            "prompt": "Find all active orders with total amount greater than 100 joined with customers",
            "spec": {
                "table": "orders",
                "columns": ["id", "customer_id", "total_amount", "status"],
                "joins": [
                    {
                        "table": "customers",
                        "type": "INNER",
                        "left_table": "orders",
                        "left_col": "customer_id",
                        "right_col": "id",
                    }
                ],
                "filters": [
                    {"column": "status", "op": "=", "value": "active"},
                    {"column": "total_amount", "op": ">", "value": 100},
                ],
                "filter_join": "AND",
                "having": [],
                "order_by": [],
                "limit": 50,
                "offset": 0,
                "distinct": False,
            },
        },
        {
            "prompt": "Count users grouped by country with count greater than 5",
            "spec": {
                "table": "users",
                "columns": [
                    "country",
                    {"column": "id", "agg": "COUNT", "alias": "user_count"},
                ],
                "joins": [],
                "filters": [],
                "filter_join": "AND",
                "having": [{"column": "user_count", "op": ">", "value": 5}],
                "order_by": [{"column": "user_count", "direction": "DESC"}],
                "limit": 50,
                "offset": 0,
                "distinct": False,
            },
        },
    ]


def build_system_prompt(schema_str: str, dialect: str = "postgres") -> str:
    """Builds the system instruction prompt grounding the model in the visual QuerySpec AST."""
    exemplars = json.dumps(get_few_shot_exemplars(), indent=2)
    return (
        "You are an expert natural language to SQL and Visual Query AST compiler.\n"
        "Your task is to translate the user prompt into a valid QuerySpec JSON AST.\n"
        f"Target SQL Dialect: {dialect}\n\n"
        f"{schema_str}\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "1. Output ONLY a valid JSON object matching the QuerySpec schema.\n"
        "2. Do NOT wrap in markdown code blocks like ```json ... ```. Return raw JSON.\n"
        "3. Supported fields in QuerySpec:\n"
        "   - table: string (the primary base table)\n"
        '   - columns: list of string column names or objects with {"column": str, "agg": str, "alias": str}\n'
        '   - joins: list of objects with {"table": str, "type": "INNER"|"LEFT"|"RIGHT"|"FULL", "left_table": str, "left_col": str, "right_col": str}\n'
        '   - filters: list of objects with {"column": str, "op": "="|"!="|">"|"<"|">="|"<="|"LIKE"|"IN"|"IS NULL"|"IS NOT NULL", "value": any}\n'
        '   - filter_join: "AND" | "OR"\n'
        '   - having: list of objects with {"column": str, "op": str, "value": any}\n'
        '   - order_by: list of objects with {"column": str, "direction": "ASC"|"DESC"}\n'
        "   - limit: integer\n"
        "   - offset: integer\n"
        "   - distinct: boolean\n"
        '   - vector_search: optional object with {"column": str, "query_vector": list[float] | null, "query_text": str | null, "top_k": int, "metric": str}\n\n'
        f"FEW-SHOT EXAMPLES:\n{exemplars}\n"
    )


def build_user_prompt(prompt: str) -> str:
    """Builds user prompt asking for QuerySpec translation."""
    return f'Translate this request into QuerySpec JSON:\n"{prompt}"'


def build_explain_prompt(query_spec: dict[str, Any], dialect: str = "postgres") -> str:
    """Builds prompt asking the model to explain a visual QuerySpec in plain human terms."""
    spec_json = json.dumps(query_spec, indent=2)
    return (
        "You are an expert SQL educator and query analyst.\n"
        f"Target Dialect: {dialect}\n"
        "Analyze this QuerySpec JSON AST and explain its business intent, data flow, filtering, and aggregation in plain, accessible English.\n"
        "Output ONLY a JSON object with this exact structure:\n"
        "{\n"
        '  "summary": "One sentence high-level summary",\n'
        '  "explanation": "Clear 2-3 paragraph explanation of the query operation",\n'
        '  "steps": ["Step 1...", "Step 2...", "Step 3..."]\n'
        "}\n\n"
        f"QuerySpec:\n{spec_json}"
    )
