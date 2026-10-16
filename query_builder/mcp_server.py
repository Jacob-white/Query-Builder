"""
Model Context Protocol (MCP) Server for Query-Builder.
======================================================
Exposes Query-Builder capabilities over standard JSON-RPC 2.0 protocol (stdio / SSE)
for integration with AI developer tools, assistants, and agentic environments
(Claude Desktop, Cursor, Gemini CLI, Windsurf, LangChain, AutoGen).
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, TextIO

from query_builder import __version__
from query_builder.advisor import analyze_query_performance, recommend_indexes
from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import QueryCompiler
from query_builder.exceptions import QueryBuilderError, SecurityError
from query_builder.explain import estimate_plan_from_spec
from query_builder.join_solver import find_join_path
from query_builder.models import QuerySpec
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.security import calculate_ast_complexity, scrub_secrets

if TYPE_CHECKING:
    from query_builder.connectors.async_base import AsyncBaseConnector
    from query_builder.connectors.base import BaseConnector
    from query_builder.semantic import SemanticRegistry

MCP_PROTOCOL_VERSION = "2024-11-05"


def _run_coroutine_safely(coro: Any) -> Any:
    """Executes a coroutine safely whether or not an event loop is already running."""
    import asyncio
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


SERVER_CAPABILITIES = {
    "tools": {
        "listChanged": False,
    },
    "resources": {
        "subscribe": False,
        "listChanged": False,
    },
}

RESOURCES = [
    {
        "uri": "query-builder://schema/catalog",
        "name": "Database Schema Catalog",
        "description": "Active database schema snapshot including tables, columns, data types, and foreign keys.",
        "mimeType": "application/json",
    },
    {
        "uri": "query-builder://schema/queryspec",
        "name": "QuerySpec JSON Schema",
        "description": "Canonical JSON Schema for declarative QuerySpec AST and supported operators.",
        "mimeType": "application/json",
    },
    {
        "uri": "query-builder://semantic/metrics",
        "name": "Semantic Metrics & Dimensions",
        "description": "Registered business metrics, calculated dimensions, and aggregations.",
        "mimeType": "application/json",
    },
]

_SPEC_SCHEMA: dict[str, Any] = {
    **QuerySpec.json_schema(),
    "description": "Declarative QuerySpec dictionary (table, columns, joins, filters, order_by, limit, etc.)",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_builder_compile",
        "description": "Compiles a declarative JSON QuerySpec into safe, parameterized SQL with multi-dialect support.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": _SPEC_SCHEMA,
                "dialect": {
                    "type": "string",
                    "description": "Target SQL dialect (postgres, snowflake, mysql, sqlite, mssql, duckdb, etc.)",
                    "default": "postgres",
                },
            },
            "required": ["spec"],
        },
    },
    {
        "name": "query_builder_validate",
        "description": "Strictly validates raw SQL or QuerySpec against AST security policies (blocking DDL/DML injection, unauthorized schema access).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Raw SQL query string to validate for read-only AST safety.",
                },
                "spec": _SPEC_SCHEMA,
                "dialect": {
                    "type": "string",
                    "description": "Target SQL dialect when compiling spec (default: 'postgres').",
                    "default": "postgres",
                },
            },
        },
    },
    {
        "name": "query_builder_explain_and_advise",
        "description": "Estimates query execution plan complexity, identifies missing indexes, and recommends performance optimizations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": _SPEC_SCHEMA,
                "dialect": {
                    "type": "string",
                    "description": "Target SQL dialect. Defaults to 'postgres'.",
                    "default": "postgres",
                },
            },
            "required": ["spec"],
        },
    },
    {
        "name": "query_builder_get_complexity",
        "description": "Calculates normalized AST complexity score and Cartesian product risks for a QuerySpec.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": _SPEC_SCHEMA,
            },
            "required": ["spec"],
        },
    },
    {
        "name": "query_builder_introspect",
        "description": "Inspects schema tables, column types, and foreign keys against configured connector.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "connector": {
                    "type": "string",
                    "description": "Registered connector identifier (e.g. 'sqlite', 'duckdb', 'postgres'). Defaults to 'sqlite'.",
                    "default": "sqlite",
                },
                "config": {
                    "type": "object",
                    "description": "Optional connector configuration dictionary (e.g. {'database': ':memory:'}).",
                },
                "filter_sensitive": {
                    "type": "boolean",
                    "description": "Filter sensitive system and auth tables. Defaults to true.",
                    "default": True,
                },
            },
        },
    },
    {
        "name": "query_builder_execute",
        "description": "Safely executes read-only queries with AST limits and dialect parameterized bindings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": _SPEC_SCHEMA,
                "sql": {
                    "type": "string",
                    "description": "Raw SQL query string (enforced read-only by AST validator).",
                },
                "params": {
                    "type": "array",
                    "description": "Optional bind parameters for parameterized query execution.",
                },
                "connector": {
                    "type": "string",
                    "description": "Registered connector identifier. Defaults to 'sqlite'.",
                    "default": "sqlite",
                },
                "config": {
                    "type": "object",
                    "description": "Optional connector configuration dictionary.",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum number of rows to return (default: 50).",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "query_builder_join_path",
        "description": "Exposes BFS graph-based join solver to find relational paths between tables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "active_tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of currently active table names in the query.",
                },
                "target_table": {
                    "type": "string",
                    "description": "Target table name to join with active tables.",
                },
                "schema": {
                    "type": "object",
                    "description": "Optional schema snapshot dictionary containing tables and foreign keys.",
                },
                "join_type": {
                    "type": "string",
                    "description": "Default SQL join type (e.g. 'LEFT JOIN', 'INNER JOIN'). Defaults to 'LEFT JOIN'.",
                    "default": "LEFT JOIN",
                },
            },
            "required": ["active_tables", "target_table"],
        },
    },
]


class McpServer:
    """Standard Model Context Protocol JSON-RPC server running over stdio."""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        *,
        connector: BaseConnector | AsyncBaseConnector | str | None = None,
        connector_config: dict[str, Any] | None = None,
        security_policy: SecurityPolicy | None = None,
        tenant_context: TenantContext | None = None,
        semantic_registry: SemanticRegistry | None = None,
        lock_connection: bool | None = None,
    ) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.connector = connector
        self.connector_config = connector_config or {}
        self.security_policy = security_policy
        self.tenant_context = tenant_context
        self.semantic_registry = semantic_registry
        if lock_connection is None:
            self.lock_connection = bool(connector is not None)
        else:
            self.lock_connection = bool(lock_connection)

    def get_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = copy.deepcopy(TOOLS)
        if self.lock_connection:
            for t in tools:
                if t.get("name") in (
                    "query_builder_introspect",
                    "query_builder_execute",
                ):
                    schema = t.get("inputSchema")
                    if isinstance(schema, dict):
                        props = schema.get("properties")
                        if isinstance(props, dict):
                            props.pop("connector", None)
                            props.pop("config", None)
                        req = schema.get("required")
                        if isinstance(req, list):
                            if "connector" in req:
                                req.remove("connector")
                            if "config" in req:
                                req.remove("config")
        return tools

    def _resolve_connector(
        self,
        connector_name: str = "sqlite",
        config: dict[str, Any] | None = None,
    ) -> Any:
        from query_builder.connectors import ConnectorRegistry

        if self.lock_connection:
            if self.connector is not None:
                if isinstance(self.connector, str):
                    return ConnectorRegistry.get(
                        self.connector, **self.connector_config
                    )
                return self.connector
            return ConnectorRegistry.get("sqlite", **self.connector_config)
        return ConnectorRegistry.get(connector_name, **(config or {}))

    def _read_resource(self, uri: str) -> str:
        if uri == "query-builder://schema/catalog":
            connector = self._resolve_connector()
            from query_builder.connectors import AsyncBaseConnector

            if isinstance(connector, AsyncBaseConnector):
                snapshot = _run_coroutine_safely(
                    connector.introspect_schema(filter_sensitive=True)
                )
            else:
                snapshot = connector.introspect_schema(filter_sensitive=True)

            if is_dataclass(snapshot) and not isinstance(snapshot, type):
                snap_dict = asdict(snapshot)
            elif hasattr(snapshot, "to_dict"):
                snap_dict = snapshot.to_dict()
            elif isinstance(snapshot, dict):
                snap_dict = snapshot
            else:
                snap_dict = {"tables": {}}

            if (
                self.security_policy
                and "tables" in snap_dict
                and isinstance(snap_dict["tables"], dict)
            ):
                allowed = (
                    set(self.security_policy.allowed_tables)
                    if self.security_policy.allowed_tables is not None
                    else None
                )
                restricted = set(self.security_policy.restricted_tables or [])
                snap_dict["tables"] = {
                    t: m
                    for t, m in snap_dict["tables"].items()
                    if (allowed is None or t in allowed) and t not in restricted
                }
            return json.dumps(snap_dict, indent=2)

        if uri == "query-builder://schema/queryspec":
            return json.dumps(QuerySpec.json_schema(), indent=2)

        if uri == "query-builder://semantic/metrics":
            if self.semantic_registry:
                metrics = [m.to_dict() for m in self.semantic_registry.list_metrics()]
                models = [m.to_dict() for m in self.semantic_registry.list_models()]
                payload = {"metrics": metrics, "models": models}
            else:
                payload = {"metrics": [], "models": []}
            return json.dumps(payload, indent=2)

        raise QueryBuilderError(f"Resource not found: '{uri}'")

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatches a single JSON-RPC 2.0 request."""
        if not isinstance(req, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: expected JSON-RPC 2.0 object dictionary.",
                },
            }

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": SERVER_CAPABILITIES,
                    "serverInfo": {
                        "name": "query-builder",
                        "version": __version__,
                    },
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tools()},
            }

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": RESOURCES},
            }

        if method == "resources/read":
            uri = str(params.get("uri", ""))
            try:
                content_text = self._read_resource(uri)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": content_text,
                            }
                        ]
                    },
                }
            except Exception as e:  # noqa: BLE001
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Invalid params: {e!s}",
                    },
                }

        if method == "tools/call":
            tool_name = str(params.get("name"))
            arguments = params.get("arguments") or {}
            try:
                content = self._dispatch_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(content, indent=2)}
                        ],
                        "isError": False,
                    },
                }
            except Exception as e:  # noqa: BLE001
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error: {type(e).__name__}: {e!s}",
                            }
                        ],
                        "isError": True,
                    },
                }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: '{method}'"},
        }

    def _dispatch_tool(self, name: str, args: dict[str, Any]) -> Any:
        if self.lock_connection and ("connector" in args or "config" in args):
            raise SecurityError(
                "Specifying 'connector' or 'config' is forbidden in locked connection mode."
            )

        if name in (
            "query_builder_compile",
            "query_builder_execute",
            "query_builder_explain_and_advise",
        ):
            spec = args.get("spec")
            if spec:
                if isinstance(spec, str):
                    spec = json.loads(spec)
                if self.security_policy is not None or self.tenant_context is not None:
                    spec = apply_security_policy(
                        spec, context=self.tenant_context, policy=self.security_policy
                    )
                args = dict(args)
                args["spec"] = spec

        if name == "query_builder_compile":
            spec = args.get("spec", {})
            if isinstance(spec, str):
                spec = json.loads(spec)
            dialect = args.get("dialect", "postgres")
            compiler = QueryCompiler(spec, dialect=dialect)
            sql, params, count_sql, count_params = compiler.compile()
            return {
                "sql": sql,
                "params": scrub_secrets(params),
                "count_sql": count_sql,
                "count_params": scrub_secrets(count_params),
                "dialect": dialect,
            }

        if name == "query_builder_validate":
            sql = args.get("sql", "")
            spec = args.get("spec")
            if not sql and spec:
                if isinstance(spec, str):
                    spec = json.loads(spec)
                dialect = args.get("dialect", "postgres")
                compiler = QueryCompiler(spec, dialect=dialect)
                sql, _, _, _ = compiler.compile()

            res = validate_sql_ast(sql)
            if isinstance(res, dict):
                return res
            return {
                "valid": getattr(res, "valid", True),
                "is_read_only": getattr(res, "is_read_only", True),
                "statement_type": getattr(res, "statement_type", "SELECT"),
                "injection_risk": getattr(res, "injection_risk", "NONE"),
                "violations": getattr(res, "violations", []),
                "message": getattr(res, "message", ""),
            }

        if name == "query_builder_explain_and_advise":
            spec = args.get("spec", {})
            if isinstance(spec, str):
                spec = json.loads(spec)
            dialect = args.get("dialect", "postgres")
            compiler = QueryCompiler(spec, dialect=dialect)
            sql, _, _, _ = compiler.compile()
            plan = estimate_plan_from_spec(spec)
            perf = analyze_query_performance(spec, sql=sql, dialect=dialect)
            recs = recommend_indexes(spec)
            return {
                "sql": sql,
                "plan": plan.to_dict() if hasattr(plan, "to_dict") else plan,
                "performance": perf,
                "recommended_indexes": recs,
            }

        if name == "query_builder_get_complexity":
            spec = args.get("spec", {})
            if isinstance(spec, str):
                spec = json.loads(spec)
            score = calculate_ast_complexity(spec)
            return {
                "complexity_score": score,
                "is_safe": score < 100,
            }

        if name == "query_builder_introspect":
            connector_name = args.get("connector", "sqlite")
            config = args.get("config") or {}
            if isinstance(config, str):
                config = json.loads(config)
            filter_sensitive = bool(args.get("filter_sensitive", True))

            from query_builder.connectors import AsyncBaseConnector

            connector = self._resolve_connector(connector_name, config)
            if isinstance(connector, AsyncBaseConnector):
                snapshot = _run_coroutine_safely(
                    connector.introspect_schema(filter_sensitive=filter_sensitive)
                )
            else:
                snapshot = connector.introspect_schema(
                    filter_sensitive=filter_sensitive
                )

            if is_dataclass(snapshot) and not isinstance(snapshot, type):
                snap_dict = asdict(snapshot)
            elif hasattr(snapshot, "to_dict"):
                snap_dict = snapshot.to_dict()
            elif isinstance(snapshot, dict):
                snap_dict = snapshot
            else:
                snap_dict = {"tables": {}}

            if (
                self.security_policy
                and "tables" in snap_dict
                and isinstance(snap_dict["tables"], dict)
            ):
                allowed = (
                    set(self.security_policy.allowed_tables)
                    if self.security_policy.allowed_tables is not None
                    else None
                )
                restricted = set(self.security_policy.restricted_tables or [])
                snap_dict["tables"] = {
                    t: m
                    for t, m in snap_dict["tables"].items()
                    if (allowed is None or t in allowed) and t not in restricted
                }
            return snap_dict

        if name == "query_builder_execute":
            spec = args.get("spec")
            raw_sql = args.get("sql")
            params = args.get("params") or []
            connector_name = args.get("connector", "sqlite")
            config = args.get("config") or {}
            max_rows = args.get("max_rows", 50)

            if isinstance(spec, str):
                spec = json.loads(spec)
            if isinstance(config, str):
                config = json.loads(config)

            if not spec and not raw_sql:
                raise QueryBuilderError("Either 'spec' or 'sql' must be provided.")

            # Validate AST safety on raw SQL
            if raw_sql:
                if self.tenant_context is not None or self.security_policy is not None:
                    raise SecurityError(
                        "Raw SQL execution is forbidden when a security policy or tenant context is active. Use 'spec' instead."
                    )
                val_res = validate_sql_ast(raw_sql)
                if not val_res.get("valid") or not val_res.get("is_read_only"):
                    violations = val_res.get(
                        "violations", ["Query rejected: Non-read-only statement."]
                    )
                    raise QueryBuilderError(
                        f"Security violation: {'; '.join(violations)}"
                    )

            # Validate AST complexity on spec
            if spec:
                score = calculate_ast_complexity(spec)
                if score > 100:
                    raise QueryBuilderError(
                        f"QuerySpec AST complexity score ({score}) exceeds maximum safe threshold (100)."
                    )
                if not spec.get("limit") or spec["limit"] > max_rows:
                    spec = dict(spec)
                    spec["limit"] = max_rows

            from query_builder.connectors import AsyncBaseConnector

            connector = self._resolve_connector(connector_name, config)
            if isinstance(connector, AsyncBaseConnector):
                res = _run_coroutine_safely(
                    connector.execute(spec=spec, sql=raw_sql, params=params)
                )
            else:
                res = connector.execute(spec=spec, sql=raw_sql, params=params)

            if hasattr(res, "to_dict"):
                res_dict = res.to_dict()
            elif isinstance(res, dict):
                res_dict = dict(res)
            else:
                res_dict = {
                    "columns": getattr(res, "columns", []),
                    "rows": getattr(res, "rows", []),
                    "count": getattr(res, "count", len(getattr(res, "rows", []))),
                }

            # Enforce max_rows limit ceiling on returned rows
            if "rows" in res_dict and len(res_dict["rows"]) > max_rows:
                res_dict["rows"] = res_dict["rows"][:max_rows]
                res_dict["truncated"] = True

            return res_dict

        if name == "query_builder_join_path":
            active_tables = args.get("active_tables", [])
            target_table = args.get("target_table", "")
            schema_data = args.get("schema")
            join_type = args.get("join_type", "LEFT JOIN")

            if isinstance(schema_data, str):
                schema_data = json.loads(schema_data)
            if isinstance(active_tables, str):
                active_tables = [
                    t.strip() for t in active_tables.split(",") if t.strip()
                ]

            if not active_tables or not target_table:
                raise QueryBuilderError(
                    "Both 'active_tables' and 'target_table' are required."
                )

            path = find_join_path(
                active_tables,
                target_table,
                schema_data=schema_data,
                default_join_type=join_type,
            )
            return {
                "path": path,
                "active_tables": active_tables,
                "target_table": target_table,
            }

        raise QueryBuilderError(f"Unknown tool name: '{name}'")

    def run_stdio(self) -> None:
        """Reads newline-delimited JSON-RPC from stdin and writes responses to stdout."""
        for line in self.stdin:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                req = json.loads(line_str)
                resp = self.handle_request(req)
                if resp is not None:
                    self.stdout.write(json.dumps(resp) + "\n")
                    self.stdout.flush()
            except Exception as e:  # noqa: BLE001
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e!s}"},
                }
                self.stdout.write(json.dumps(err_resp) + "\n")
                self.stdout.flush()


def main() -> int:
    """Console-script entry point (`query-builder-mcp`): serve MCP over stdio."""
    McpServer().run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
