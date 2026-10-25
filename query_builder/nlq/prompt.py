"""
Prompt construction, schema serialization, and few-shot exemplars for NLQ engine.
"""

from __future__ import annotations

import json
from typing import Any


def serialize_schema_for_prompt(
    schema: dict[str, Any] | None,
    semantic: Any = None,
) -> str:
    """Serializes a database schema dictionary and optional semantic layer metadata into concise markdown text for LLM prompts."""
    lines: list[str] = []
    if schema:
        lines.append("Database Schema:")
        tables = schema.get("tables", schema)
        top_fks_by_table: dict[str, list[str]] = {}
        raw_top_fks = schema.get("foreign_keys", []) if isinstance(schema, dict) else []
        if isinstance(raw_top_fks, list):
            for fk in raw_top_fks:
                if isinstance(fk, dict):
                    src_tbl = fk.get("table", "")
                    from_col = fk.get("column", fk.get("from_column", ""))
                    to_tbl = fk.get(
                        "foreign_table", fk.get("target_table", fk.get("to_table", ""))
                    )
                    to_col = fk.get(
                        "foreign_column",
                        fk.get("target_column", fk.get("to_column", "")),
                    )
                    if src_tbl and from_col and to_tbl:
                        top_fks_by_table.setdefault(str(src_tbl), []).append(
                            f"{from_col} -> {to_tbl}.{to_col or 'id'}"
                        )

        if isinstance(tables, dict):
            table_items = list(tables.items())
            max_detailed = 90
            for idx, (tbl_name, tbl_data) in enumerate(table_items):
                if not isinstance(tbl_data, dict):
                    continue
                cols_info: list[str] = []
                columns = tbl_data.get("columns", {})
                is_compact = (
                    len(table_items) > max_detailed
                    and idx >= max_detailed
                    and tbl_name not in top_fks_by_table
                )
                if isinstance(columns, dict):
                    for col_name, col_meta in columns.items():
                        if is_compact:
                            cols_info.append(str(col_name))
                        elif isinstance(col_meta, dict):
                            col_type = col_meta.get(
                                "data_type", col_meta.get("type", "TEXT")
                            )
                            pk = (
                                " (PK)"
                                if col_meta.get("primary_key")
                                or col_meta.get("is_primary")
                                else ""
                            )
                            cols_info.append(f"{col_name}: {col_type}{pk}")
                        else:
                            cols_info.append(f"{col_name}: {col_meta}")
                elif isinstance(columns, list):
                    for col in columns:
                        if isinstance(col, dict):
                            cname = col.get("name", "unknown")
                            if is_compact:
                                cols_info.append(str(cname))
                            else:
                                ctype = col.get("data_type", col.get("type", "TEXT"))
                                pk = (
                                    " (PK)"
                                    if col.get("primary_key") or col.get("is_primary")
                                    else ""
                                )
                                cols_info.append(f"{cname}: {ctype}{pk}")
                        elif isinstance(col, str):
                            cols_info.append(col)

                if is_compact and len(cols_info) > 12:
                    cols_info = [*cols_info[:12], "..."]

                fks_info: list[str] = list(top_fks_by_table.get(tbl_name, []))
                fks = tbl_data.get("foreign_keys", [])
                if isinstance(fks, list):
                    for fk in fks:
                        if isinstance(fk, dict):
                            from_col = fk.get("column", fk.get("from_column", ""))
                            to_tbl = fk.get(
                                "target_table",
                                fk.get("foreign_table", fk.get("to_table", "")),
                            )
                            to_col = fk.get(
                                "target_column",
                                fk.get("foreign_column", fk.get("to_column", "")),
                            )
                            if from_col and to_tbl:
                                entry_str = f"{from_col} -> {to_tbl}.{to_col or 'id'}"
                                if entry_str not in fks_info:
                                    fks_info.append(entry_str)

                col_str = ", ".join(cols_info) if cols_info else "no columns listed"
                fk_str = f" | FK: {', '.join(fks_info)}" if fks_info else ""
                lines.append(f"- Table `{tbl_name}`: [{col_str}]{fk_str}")
    else:
        lines.append(
            "Schema: No explicit schema provided. Infer plausible table and column identifiers from prompt."
        )

    if semantic is not None:
        from query_builder.semantic import resolve_semantic_registry

        reg = resolve_semantic_registry(semantic)
        if reg is not None:
            models = reg.list_models()
            metrics = reg.list_metrics()
            if models or metrics:
                lines.append("\nSemantic Metrics & Dimensions:")
                for m in models:
                    lines.append(f"- Model `{m.name}` (Table: `{m.table_name}`):")
                    for met in m.metrics:
                        desc = f" - {met.description}" if met.description else ""
                        lines.append(
                            f"  * Metric `{met.name}`: {met.title} [{met.aggregation} over `{met.sql_expression}`]{desc}"
                        )
                    for dim in m.dimensions:
                        desc = f" - {dim.description}" if dim.description else ""
                        lines.append(
                            f"  * Dimension `{dim.name}`: {dim.title} [`{dim.sql_expression}` ({dim.data_type})]{desc}"
                        )
                # Any standalone metrics not bound to listed models
                model_metric_names = {met.name for m in models for met in m.metrics}
                standalone_metrics = [
                    met for met in metrics if met.name not in model_metric_names
                ]
                for met in standalone_metrics:
                    desc = f" - {met.description}" if met.description else ""
                    lines.append(
                        f"- Metric `{met.name}`: {met.title} [{met.aggregation} over `{met.sql_expression}` on `{met.table or 'unknown'}`]{desc}"
                    )

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
                "having": [{"column": "id", "agg": "COUNT", "op": ">", "value": 5}],
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
        '   - columns: list of string column names or objects with {"column": str, "agg": str, "alias": str} (use [] to select all columns, or pick 4-8 most relevant columns)\n'
        '   - joins: list of objects with {"table": str, "type": "INNER"|"LEFT"|"RIGHT"|"FULL", "left_table": str, "left_col": str, "right_col": str}\n'
        '   - filters: list of objects with {"column": str, "op": "="|"!="|">"|"<"|">="|"<="|"LIKE"|"ILIKE"|"IN"|"IS NULL"|"IS NOT NULL", "value": any}\n'
        '   - filter_join: "AND" | "OR"\n'
        '   - having: list of objects with {"column": str, "agg": "COUNT"|"SUM"|"AVG"|"MIN"|"MAX", "op": "="|"!="|">"|"<"|">="|"<=", "value": any}\n'
        '   - order_by: list of objects with {"column": str, "direction": "ASC"|"DESC"}\n'
        "   - limit: integer\n"
        "   - offset: integer\n"
        "   - distinct: boolean\n"
        '   - vector_search: optional object with {"column": str, "query_vector": list[float] | null, "query_text": str | null, "top_k": int, "metric": str}\n'
        "   - explanation: concise 1-2 sentence plain-English summary of what the generated query does\n"
        "   - follow_ups: list of 3 short natural-language follow-up prompts the user can click next to refine this query (e.g. adding a filter, sorting, grouping, joining a related table, or changing the limit)\n"
        "4. CRITICAL SCHEMA GROUNDING:\n"
        "   - When a Database Schema is listed above, you MUST ONLY use table names and column names that exist in that Database Schema.\n"
        "   - NEVER use example table names ('customers', 'orders', 'users') unless they actually exist in the Database Schema above.\n"
        "   - If the user refers to generic entities (e.g. 'customers', 'firms', 'records', 'items', 'balance', 'amount', 'status'), map them to the closest matching table and columns in the Database Schema.\n"
        "   - When qualifying column names with a table prefix (e.g., 'table_name.column_name'), ALWAYS use the exact full table name from the schema (never invent short aliases like 'u.id' or 'hp.id').\n"
        "5. MULTI-SHOT CONVERSATIONAL REFINEMENT:\n"
        "   - When a Current Active QuerySpec and/or Conversation History is provided in the user prompt, treat follow-up instructions (e.g. 'also filter...', 'now sort by...', 'add column...', 'join with...', 'only show...', 'group by...', 'limit to 10') as incremental refinements to the Current Active QuerySpec.\n"
        "   - Preserve existing tables, joins, columns, filters, and sorts from the Current Active QuerySpec unless the user explicitly asks to remove them or query a different base table.\n\n"
        f"FEW-SHOT EXAMPLES:\n{exemplars}\n"
    )


def build_user_prompt(
    prompt: str,
    current_spec: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Builds user prompt asking for QuerySpec translation, optionally grounded in multi-turn history."""
    has_history = isinstance(history, list) and len(history) > 0
    has_spec = (
        isinstance(current_spec, dict)
        and bool(current_spec.get("table"))
        and (
            has_history
            or bool(current_spec.get("columns"))
            or bool(current_spec.get("joins"))
            or bool(current_spec.get("filters"))
            or bool(current_spec.get("order_by"))
        )
    )
    if not has_history and not has_spec:
        return f'Translate this request into QuerySpec JSON:\n"{prompt}"'

    parts: list[str] = []
    if has_history and history:
        parts.append("CONVERSATION HISTORY (oldest to newest):")
        for idx, turn in enumerate(history[-6:], start=1):
            if isinstance(turn, dict):
                u_p = turn.get("prompt") or turn.get("content") or ""
                t_exp = turn.get("explanation") or ""
                t_spec = turn.get("spec")
                spec_summary = json.dumps(t_spec) if isinstance(t_spec, dict) else ""
                parts.append(f"Turn {idx} User: {u_p!r}")
                if t_exp:
                    parts.append(f"Turn {idx} Explanation: {t_exp}")
                if spec_summary:
                    parts.append(f"Turn {idx} Spec: {spec_summary}")
        parts.append("")

    if isinstance(current_spec, dict) and current_spec.get("table"):
        compact_spec = {
            k: v
            for k, v in current_spec.items()
            if k
            in {
                "table",
                "columns",
                "joins",
                "filters",
                "filter_join",
                "having",
                "order_by",
                "limit",
                "distinct",
            }
        }
        parts.append(
            f"CURRENT ACTIVE QUERYSPEC ON CANVAS:\n{json.dumps(compact_spec, indent=2)}\n"
        )

    parts.append(
        "Translate or refine the query according to this new user request (evolve the Current Active QuerySpec if this is a follow-up refinement, or switch tables if the user asks for a different dataset):\n"
        f'"{prompt}"'
    )
    return "\n".join(parts)


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
