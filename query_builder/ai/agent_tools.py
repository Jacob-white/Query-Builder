"""
AI Agent Tool Calling Specifications & Universal Tool Execution Handler.
=========================================================================
Generates standardized tool/function definitions for AI agentic frameworks:
- OpenAI Function Calling / Tools (gpt-4o, o3, etc.)
- Anthropic Claude Tools (Claude 3.5 Sonnet, Claude 3 Opus, etc.)
- Google Gemini Function Calling (Gemini 1.5 Pro/Flash, Gemini 2.0, etc.)
- LangChain BaseTool definitions
- Model Context Protocol (MCP) Tool schemas
"""

from __future__ import annotations

import json
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import QueryCompiler
from query_builder.nlq.prompt import serialize_schema_for_prompt
from query_builder.nlq.service import NlqService
from query_builder.nlq.validator import NlqAstValidator

TOOL_SCHEMAS_BASE = [
    {
        "name": "build_query",
        "description": (
            "Translates a natural language data request or intent into a schema-grounded, "
            "syntactically valid SQL query and visual QuerySpec AST for any SQL dialect. "
            "Automatically resolves multi-table joins, aggregates, and security constraints."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "The user's query intent in plain English (e.g. 'Show total revenue grouped by category for completed orders in 2024').",
                },
                "dialect": {
                    "type": "string",
                    "description": "Target SQL dialect (e.g. 'postgres', 'snowflake', 'bigquery', 'mysql', 'sqlite', 'duckdb'). Defaults to 'postgres'.",
                    "default": "postgres",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return (default: 50).",
                    "default": 50,
                },
                "options": {
                    "type": "object",
                    "description": "Optional translation and styling parameters.",
                    "properties": {
                        "distinct": {
                            "type": "boolean",
                            "description": "Whether to enforce SELECT DISTINCT.",
                        },
                        "explain": {
                            "type": "boolean",
                            "description": "Whether to return plain-English explanation.",
                        },
                    },
                },
            },
            "required": ["intent"],
        },
    },
    {
        "name": "validate_and_compile_query",
        "description": (
            "Validates an AST or SQL query against database schema and AST security policies "
            "(blocking SQL injection and data mutations), resolves table joins, and compiles "
            "into dialect-optimized SQL."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "object",
                    "description": "QuerySpec AST dictionary containing table, columns, joins, filters, order_by, limit.",
                },
                "sql": {
                    "type": "string",
                    "description": "Raw SQL query to parse, validate, and compile.",
                },
                "dialect": {
                    "type": "string",
                    "description": "Target SQL dialect. Defaults to 'postgres'.",
                    "default": "postgres",
                },
            },
        },
    },
    {
        "name": "get_schema_catalog",
        "description": (
            "Retrieves the active database schema catalog, listing available tables, columns, "
            "data types, primary keys, and foreign key relationships to ground query generation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of table names to filter the schema catalog for.",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Output format: 'markdown' for LLM prompt context or 'json' for raw metadata.",
                    "default": "markdown",
                },
            },
        },
    },
    {
        "name": "explain_query",
        "description": (
            "Produces a natural language explanation of a SQL query or QuerySpec AST, "
            "detailing the primary table, joins, filters, and projections in plain English."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL statement to explain.",
                },
                "spec": {
                    "type": "object",
                    "description": "QuerySpec AST dictionary to explain.",
                },
                "dialect": {
                    "type": "string",
                    "description": "SQL dialect of the query. Defaults to 'postgres'.",
                    "default": "postgres",
                },
            },
        },
    },
]


def get_agent_tool_definitions(
    format: str = "openai",
    schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Returns tool definitions formatted for the target AI agent framework.

    Parameters:
        format: Target format ('openai', 'anthropic', 'gemini', 'langchain', 'mcp').
        schema: Optional schema dictionary to attach to tool descriptions.
    """
    fmt = format.lower().strip()
    tools = TOOL_SCHEMAS_BASE

    if fmt == "openai":
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    elif fmt == "anthropic":
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

    elif fmt == "gemini":
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in tools
        ]

    elif fmt == "langchain":
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "args_schema": t["parameters"],
            }
            for t in tools
        ]

    elif fmt == "mcp":
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["parameters"],
            }
            for t in tools
        ]

    else:
        raise ValueError(
            f"Unsupported agent tool format '{format}'. Supported formats: 'openai', 'anthropic', 'gemini', 'langchain', 'mcp'."
        )


def execute_agent_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | str,
    schema: dict[str, Any] | None = None,
    dialect: str = "postgres",
    nlq_service: NlqService | None = None,
) -> dict[str, Any]:
    """
    Universally executes an AI agent's tool call against Query-Builder.

    Parameters:
        tool_name: Name of tool called by LLM ('build_query', 'validate_and_compile_query', 'get_schema_catalog', 'explain_query').
        arguments: Arguments dictionary or JSON string passed by the LLM.
        schema: Database schema metadata dictionary.
        dialect: Default SQL dialect.
        nlq_service: Optional preconfigured NlqService instance.
    """
    if not isinstance(tool_name, str):
        return {"success": False, "error": "Tool name must be a string."}
    name = tool_name.strip()

    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            args = parsed if isinstance(parsed, dict) else {}
        except Exception as exc:
            return {"success": False, "error": f"Invalid JSON arguments: {exc}"}
    elif isinstance(arguments, dict):
        args = dict(arguments)
    else:
        return {
            "success": False,
            "error": "Arguments must be a valid JSON string or dictionary.",
        }

    if name == "build_query":
        intent = str(args.get("intent", "")).strip()
        if not intent:
            return {"success": False, "error": "Missing required argument 'intent'."}

        target_dialect = args.get("dialect", dialect) or "postgres"
        try:
            limit = int(args.get("limit", 50))
        except (ValueError, TypeError):
            limit = 50
        svc = nlq_service or NlqService(default_provider="mock")

        res = svc.translate(
            {
                "prompt": intent,
                "schema": schema,
                "dialect": target_dialect,
            }
        )

        spec = dict(res.spec)
        spec["limit"] = limit

        # Compile to SQL
        compiler = QueryCompiler(spec, schema=schema, dialect=target_dialect)
        sql = compiler.compile()[0]

        return {
            "success": True,
            "tool": "build_query",
            "sql": sql,
            "spec": spec,
            "explanation": res.explanation,
            "confidence": res.confidence,
            "warnings": res.warnings,
            "dialect": target_dialect,
        }

    elif name == "validate_and_compile_query":
        target_dialect = args.get("dialect", dialect) or "postgres"
        spec = args.get("spec")
        raw_sql = args.get("sql")

        if not spec and not raw_sql:
            return {
                "success": False,
                "error": "Either 'spec' (QuerySpec AST) or 'sql' (SQL query string) must be provided.",
            }

        # Check raw SQL security immediately if provided
        if raw_sql:
            sec_res = validate_sql_ast(raw_sql)
            if not sec_res.get("valid"):
                violations = sec_res.get("violations", [])
                return {
                    "success": False,
                    "valid": False,
                    "security_violations": violations,
                    "error": f"Security validation failed: {'; '.join(violations)}",
                }

        if raw_sql and not spec:
            from query_builder.parser import parse_sql_to_dict

            parsed_spec = parse_sql_to_dict(raw_sql)
            if not parsed_spec:
                return {
                    "success": False,
                    "valid": False,
                    "error": f"Failed to parse SQL into QuerySpec AST: {raw_sql}",
                }
            spec = parsed_spec

        # Validate AST security
        sql_to_check = raw_sql
        if not sql_to_check:
            try:
                compiler = QueryCompiler(spec, schema=schema, dialect=target_dialect)
                sql_to_check = compiler.compile()[0]
            except Exception as exc:
                return {
                    "success": False,
                    "valid": False,
                    "error": f"Query compilation validation failed: {exc}",
                }

        sec_res = validate_sql_ast(sql_to_check)
        if not sec_res.get("valid"):
            violations = sec_res.get("violations", [])
            return {
                "success": False,
                "valid": False,
                "security_violations": violations,
                "error": f"Security validation failed: {'; '.join(violations)}",
            }

        # Validate against schema
        validator = NlqAstValidator(schema=schema)
        validated_ast, warnings = validator.validate(spec)

        compiler = QueryCompiler(validated_ast, schema=schema, dialect=target_dialect)
        sql = compiler.compile()[0]

        return {
            "success": True,
            "valid": True,
            "tool": "validate_and_compile_query",
            "sql": sql,
            "spec": validated_ast,
            "warnings": warnings,
            "dialect": target_dialect,
        }

    elif name == "get_schema_catalog":
        target_format = args.get("format", "markdown").lower()
        filter_tables = args.get("tables")

        active_schema = schema or {}
        tables_dict = active_schema.get("tables", active_schema)

        if (
            filter_tables
            and isinstance(filter_tables, list)
            and isinstance(tables_dict, dict)
        ):
            filtered_tables = {
                k: v for k, v in tables_dict.items() if k in filter_tables
            }
            schema_to_serialize = {"tables": filtered_tables}
        else:
            schema_to_serialize = active_schema

        if target_format == "json":
            return {
                "success": True,
                "tool": "get_schema_catalog",
                "format": "json",
                "schema": schema_to_serialize,
            }

        catalog_md = serialize_schema_for_prompt(schema_to_serialize)
        return {
            "success": True,
            "tool": "get_schema_catalog",
            "format": "markdown",
            "catalog": catalog_md,
        }

    elif name == "explain_query":
        target_dialect = args.get("dialect", dialect) or "postgres"
        spec = args.get("spec")
        raw_sql = args.get("sql")

        if raw_sql and not spec:
            from query_builder.parser import parse_sql_to_dict

            spec = parse_sql_to_dict(raw_sql)

        if not spec:
            return {
                "success": False,
                "error": "Query or spec to explain was not provided or could not be parsed.",
            }

        tbl = spec.get("table", "unknown")
        cols = spec.get("columns", ["*"])
        col_names = []
        for c in cols:
            if isinstance(c, dict):
                col_names.append(c.get("alias") or c.get("column", "expr"))
            else:
                col_names.append(str(c))

        joins = spec.get("joins", [])
        filters = spec.get("filters", [])
        limit = spec.get("limit")

        explanation_parts = [
            f"Queries from table `{tbl}` selecting {len(cols)} column(s): {', '.join(col_names)}."
        ]
        if joins:
            join_descs = [
                f"{j.get('type', 'JOIN')} `{j.get('table')}` on {j.get('left_col')}={j.get('right_col')}"
                for j in joins
            ]
            explanation_parts.append(f"Joins: {'; '.join(join_descs)}.")
        if filters:
            filter_descs = [
                f"{f.get('column')} {f.get('op', '=')} {f.get('value')}"
                for f in filters
            ]
            explanation_parts.append(
                f"Filtered where {spec.get('filter_join', 'AND').join(' (' + d + ')' for d in filter_descs)}."
            )
        if limit:
            explanation_parts.append(f"Limits results to top {limit} rows.")

        return {
            "success": True,
            "tool": "explain_query",
            "summary": " ".join(explanation_parts),
            "table": tbl,
            "projections": col_names,
            "joins_count": len(joins),
            "filters_count": len(filters),
            "limit": limit,
        }

    else:
        return {
            "success": False,
            "error": f"Unknown tool '{tool_name}'. Available tools: {[t['name'] for t in TOOL_SCHEMAS_BASE]}",
        }
