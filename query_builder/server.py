"""
Native HTTP Microservice & OpenAPI 3.1 Server.
==============================================
Zero-external-dependency HTTP server built on standard library ThreadingHTTPServer.
Serves OpenAPI 3.1 documentation, interactive Swagger UI at /docs, healthcheck,
and REST APIs for introspection, compilation, validation, execution, export,
templates, and telemetry.
"""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.cache import compute_cache_key, get_global_cache
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.connectors.registry import get_connector
from query_builder.dialects import DIALECTS
from query_builder.explain import estimate_plan_from_spec, normalize_explain_output
from query_builder.export import ExportError, export_dataset
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.pool import ConnectionPool
from query_builder.security import SecurityError
from query_builder.telemetry import TelemetryCollector
from query_builder.templates import TemplateError, TemplateStore


def generate_openapi_spec() -> dict[str, Any]:
    """Generates the OpenAPI 3.1.0 JSON specification document."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Query Builder API",
            "version": "1.0.0",
            "description": "Universal SQL Query Builder, Declarative Compiler, and AST Safety Microservice.",
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health Check",
                    "responses": {"200": {"description": "Server health status"}},
                }
            },
            "/openapi.json": {
                "get": {
                    "summary": "OpenAPI Specification",
                    "responses": {"200": {"description": "OpenAPI 3.1 document"}},
                }
            },
            "/docs": {
                "get": {
                    "summary": "Swagger UI Documentation",
                    "responses": {"200": {"description": "Swagger UI HTML"}},
                }
            },
            "/api/v1/introspect": {
                "post": {
                    "summary": "Introspect Database Schema",
                    "responses": {
                        "200": {"description": "Schema snapshot"},
                        "400": {"description": "Introspection error"},
                    },
                }
            },
            "/api/v1/compile": {
                "post": {
                    "summary": "Compile Query Specification",
                    "responses": {
                        "200": {"description": "Compiled SQL and parameters"},
                        "400": {"description": "Compilation error"},
                        "403": {"description": "Forbidden by security policy"},
                    },
                }
            },
            "/api/v1/validate": {
                "post": {
                    "summary": "Validate SQL AST",
                    "responses": {
                        "200": {"description": "Validation result"},
                        "400": {"description": "Validation error"},
                    },
                }
            },
            "/api/v1/execute": {
                "post": {
                    "summary": "Execute Query",
                    "responses": {
                        "200": {"description": "Query result"},
                        "400": {"description": "Execution error"},
                        "403": {"description": "Forbidden by security policy"},
                    },
                }
            },
            "/api/v1/stream": {
                "post": {
                    "summary": "Stream Query Execution via Server-Sent Events",
                    "responses": {
                        "200": {"description": "Server-Sent Events stream"},
                        "400": {"description": "Streaming error"},
                        "403": {"description": "Forbidden by security policy"},
                    },
                }
            },
            "/api/v1/explain": {
                "post": {
                    "summary": "Explain and Analyze Query Plan",
                    "responses": {
                        "200": {"description": "Normalized QueryPlanNode tree"},
                        "400": {"description": "Explain error"},
                    },
                }
            },
            "/api/v1/export": {
                "post": {
                    "summary": "Export Tabular Data",
                    "responses": {
                        "200": {"description": "Exported tabular file"},
                        "400": {"description": "Export error"},
                    },
                }
            },
            "/api/v1/templates": {
                "get": {
                    "summary": "List Templates",
                    "responses": {"200": {"description": "List of templates"}},
                },
                "post": {
                    "summary": "Create or Update Template",
                    "responses": {
                        "201": {"description": "Created template"},
                        "400": {"description": "Validation error"},
                    },
                },
            },
            "/api/v1/templates/{id}": {
                "delete": {
                    "summary": "Delete Template",
                    "responses": {
                        "200": {"description": "Deletion confirmation"},
                        "403": {"description": "Forbidden"},
                        "404": {"description": "Not found"},
                    },
                }
            },
            "/api/v1/telemetry": {
                "get": {
                    "summary": "Get Execution Telemetry Metrics",
                    "responses": {"200": {"description": "Telemetry metrics summary"}},
                }
            },
        },
        "components": {
            "schemas": {
                "VectorSearchSpec": {
                    "type": "object",
                    "properties": {
                        "vector": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Query embedding vector",
                        },
                        "column": {
                            "type": "string",
                            "default": "embedding",
                            "description": "Embedding column name",
                        },
                        "top_k": {
                            "type": "integer",
                            "default": 10,
                            "description": "Max nearest neighbors to retrieve",
                        },
                        "metric": {
                            "type": "string",
                            "enum": [
                                "cosine",
                                "euclidean",
                                "l2",
                                "dot_product",
                                "inner_product",
                            ],
                            "default": "cosine",
                            "description": "Similarity / distance metric",
                        },
                        "include_distances": {
                            "type": "boolean",
                            "default": True,
                            "description": "Whether to project _distance in output",
                        },
                        "min_score": {
                            "type": "number",
                            "description": "Optional similarity score threshold",
                        },
                    },
                    "required": ["vector"],
                },
                "HybridSearchSpec": {
                    "type": "object",
                    "properties": {
                        "vector": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Query embedding vector",
                        },
                        "vector_column": {
                            "type": "string",
                            "default": "embedding",
                            "description": "Embedding column name",
                        },
                        "query_text": {
                            "type": "string",
                            "description": "Text query for full-text search",
                        },
                        "text_columns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Text columns to search against",
                        },
                        "alpha": {
                            "type": "number",
                            "default": 0.5,
                            "description": "Hybrid weight (1.0 = pure vector, 0.0 = pure text)",
                        },
                        "fusion": {
                            "type": "string",
                            "enum": ["rrf", "linear"],
                            "default": "rrf",
                            "description": "Fusion strategy",
                        },
                        "rrf_k": {
                            "type": "integer",
                            "default": 60,
                            "description": "RRF smoothing factor",
                        },
                        "top_k": {
                            "type": "integer",
                            "default": 10,
                            "description": "Max nearest neighbors to retrieve",
                        },
                    },
                    "required": ["vector", "query_text", "text_columns"],
                },
                "QuerySpec": {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string"},
                        "columns": {"type": "array", "items": {"type": "string"}},
                        "filters": {"type": "array"},
                        "limit": {"type": "integer", "default": 50},
                        "offset": {"type": "integer", "default": 0},
                        "vector_search": {
                            "$ref": "#/components/schemas/VectorSearchSpec"
                        },
                        "hybrid_search": {
                            "$ref": "#/components/schemas/HybridSearchSpec"
                        },
                    },
                    "required": ["table"],
                },
                "QueryPlanNode": {
                    "type": "object",
                    "properties": {
                        "node_type": {"type": "string"},
                        "table": {"type": "string", "nullable": True},
                        "cost_estimate": {"type": "number"},
                        "actual_time_ms": {"type": "number", "nullable": True},
                        "rows_estimated": {"type": "integer"},
                        "rows_actual": {"type": "integer", "nullable": True},
                        "filter_predicate": {"type": "string", "nullable": True},
                        "index_name": {"type": "string", "nullable": True},
                        "cost_percentage": {"type": "number"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/QueryPlanNode"},
                        },
                    },
                    "required": [
                        "node_type",
                        "cost_estimate",
                        "rows_estimated",
                        "cost_percentage",
                    ],
                },
            }
        },
    }


def serve_swagger_ui_html() -> str:
    """Returns standalone Swagger UI HTML page embedding OpenAPI schema."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Query Builder - Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {
      window.ui = SwaggerUIBundle({
        url: '/openapi.json',
        dom_id: '#swagger-ui',
      });
    };
  </script>
</body>
</html>
"""


class QueryBuilderHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Query-Builder microservice API."""

    telemetry_collector: TelemetryCollector = TelemetryCollector()
    template_store: TemplateStore = TemplateStore()
    connection_pool: ConnectionPool | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr HTTP request logging for test cleanliness."""

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Tenant-ID",
        )

    def send_json_response(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def send_error_response(
        self, message: str, code: str = "BAD_REQUEST", status: int = 400
    ) -> None:
        self.send_json_response(
            {"error": {"code": code, "message": message}, "status": status},
            status=status,
        )

    def send_bytes_response(
        self,
        content: bytes,
        content_type: str,
        filename: str | None = None,
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if filename:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def parse_json_body(self) -> dict[str, Any]:
        content_len_header = self.headers.get("Content-Length")
        if not content_len_header:
            return {}
        try:
            length = int(content_len_header)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            self.send_json_response(
                {
                    "status": "ok",
                    "version": "1.0.0",
                    "dialects": sorted(DIALECTS.keys()),
                }
            )
            return

        if path == "/openapi.json":
            self.send_json_response(generate_openapi_spec())
            return

        if path == "/docs":
            html_bytes = serve_swagger_ui_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        if path == "/api/v1/telemetry":
            self.send_json_response(self.telemetry_collector.get_metrics())
            return

        if path == "/api/v1/templates":
            tenant_id = query.get("tenant_id", [None])[0]
            category = query.get("category", [None])[0]
            search = query.get("search", [None])[0]
            templates = self.template_store.list(
                tenant_id=tenant_id, category=category, search=search
            )
            self.send_json_response([t.to_dict() for t in templates])
            return

        self.send_error_response(
            f"Endpoint not found: {path}", code="NOT_FOUND", status=404
        )

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            body = self.parse_json_body()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.send_error_response(
                f"Invalid JSON request body: {exc}",
                code="BAD_REQUEST",
                status=400,
            )
            return

        if path == "/api/v1/introspect":
            connector_name = body.get("connector", "sqlite")
            config = body.get("config", {})
            try:
                conn = get_connector(
                    connector_name, **(config if isinstance(config, dict) else {})
                )
                snapshot = conn.introspect_schema()
                self.send_json_response(snapshot)
            except Exception as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Introspection failed: {exc}",
                    code="INTROSPECTION_ERROR",
                    status=400,
                )
            return

        if path == "/api/v1/compile":
            spec = body.get("spec")
            if not spec or not isinstance(spec, dict):
                self.send_error_response(
                    "Missing required 'spec' dictionary.",
                    code="BAD_REQUEST",
                    status=400,
                )
                return

            schema = body.get("schema")
            dialect = body.get("dialect", "postgres")
            tenant_id = body.get("tenant_id")
            policy = body.get("policy")

            try:
                active_spec = spec
                if tenant_id or policy is not None:
                    ctx = TenantContext(tenant_id=tenant_id) if tenant_id else None
                    active_spec = apply_security_policy(
                        spec,
                        schema=schema,
                        context=ctx,
                        policy=SecurityPolicy(**policy)
                        if isinstance(policy, dict)
                        else policy,
                    )

                compiler = QueryCompiler(active_spec, schema=schema, dialect=dialect)
                main_sql, params, count_sql, count_params = compiler.compile()
                self.send_json_response(
                    {
                        "sql": main_sql,
                        "params": params,
                        "count_sql": count_sql,
                        "count_params": count_params,
                        "dialect": dialect,
                    }
                )
            except SecurityError as exc:
                self.send_error_response(str(exc), code="FORBIDDEN", status=403)
            except (CompilationError, Exception) as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Compilation failed: {exc}",
                    code="COMPILATION_ERROR",
                    status=400,
                )
            return

        if path == "/api/v1/validate":
            sql = body.get("sql")
            if not sql or not isinstance(sql, str):
                self.send_error_response(
                    "Missing required 'sql' string.",
                    code="BAD_REQUEST",
                    status=400,
                )
                return

            allowed_schemas = body.get("allowed_schemas")
            try:
                result = validate_sql_ast(sql, allowed_schemas=allowed_schemas)
                self.send_json_response(result)
            except Exception as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Validation failed: {exc}",
                    code="VALIDATION_ERROR",
                    status=400,
                )
            return

        if path in ("/api/v1/execute", "/api/query"):
            spec = body.get("spec")
            sql = body.get("sql")
            connector_name = body.get("connector", "sqlite")
            config = body.get("config", {})
            tenant_id = body.get("tenant_id")
            policy = body.get("policy")
            timeout_ms = body.get("timeout_ms")
            use_cache = body.get("use_cache", False)
            cache_ttl = body.get("cache_ttl")

            if not spec and not sql:
                self.send_error_response(
                    "Either 'spec' or 'sql' must be provided.",
                    code="BAD_REQUEST",
                    status=400,
                )
                return

            cache = get_global_cache()
            cache_key = None
            if use_cache:
                target = spec if spec is not None else {"sql": sql, "params": body.get("params", [])}
                cache_key = compute_cache_key(
                    target, dialect=connector_name, tenant_id=tenant_id
                )
                cached_res = cache.get(cache_key)
                if cached_res is not None and isinstance(cached_res, dict):
                    res_copy = dict(cached_res)
                    res_copy["cached"] = True
                    self.send_json_response(res_copy)
                    return

            try:
                conn = get_connector(
                    connector_name,
                    **(config if isinstance(config, dict) else {}),
                )

                if spec is not None:
                    active_spec = spec
                    if tenant_id or policy is not None:
                        ctx = TenantContext(tenant_id=tenant_id) if tenant_id else None
                        active_spec = apply_security_policy(
                            spec,
                            context=ctx,
                            policy=SecurityPolicy(**policy)
                            if isinstance(policy, dict)
                            else policy,
                        )
                    result_data = conn.execute(
                        active_spec, statement_timeout_ms=timeout_ms
                    )
                    executed_sql = result_data.get("sql", "")
                else:
                    assert sql is not None
                    params = body.get("params", [])
                    cols, rows, latency = conn.execute_raw(sql, params)
                    result_data = {
                        "sql": sql,
                        "params": params,
                        "columns": cols,
                        "rows": rows,
                        "count": len(rows),
                        "limit": len(rows),
                        "offset": 0,
                        "latency_ms": round(latency, 2),
                        "dialect": conn.dialect_name,
                    }
                    executed_sql = sql

                result_data["cached"] = False
                if use_cache and cache_key is not None:
                    cache.set(cache_key, result_data, ttl=cache_ttl)

                self.telemetry_collector.record_execution(
                    sql=executed_sql,
                    latency_ms=result_data.get("latency_ms", 0.0),
                    row_count=result_data.get(
                        "count", len(result_data.get("rows", []))
                    ),
                    status="success",
                    dialect=result_data.get("dialect", "sqlite"),
                    tenant_id=tenant_id,
                )
                self.send_json_response(result_data)
            except SecurityError as exc:
                self.send_error_response(str(exc), code="FORBIDDEN", status=403)
            except Exception as exc:  # noqa: BLE001
                self.telemetry_collector.record_execution(
                    sql=sql or str(spec),
                    latency_ms=0.0,
                    status="error",
                    error_message=str(exc),
                    tenant_id=tenant_id,
                )
                self.send_error_response(
                    f"Execution failed: {exc}",
                    code="EXECUTION_ERROR",
                    status=400,
                )
            return

        if path in ("/api/v1/stream", "/api/query/stream"):
            spec = body.get("spec")
            sql = body.get("sql")
            connector_name = body.get("connector", "sqlite")
            config = body.get("config", {})
            tenant_id = body.get("tenant_id")
            policy = body.get("policy")
            timeout_ms = body.get("timeout_ms")
            batch_size = int(body.get("batch_size", 250))
            if batch_size <= 0:
                batch_size = 250

            if not spec and not sql:
                self.send_error_response(
                    "Either 'spec' or 'sql' must be provided.",
                    code="BAD_REQUEST",
                    status=400,
                )
                return

            try:
                conn = get_connector(
                    connector_name,
                    **(config if isinstance(config, dict) else {}),
                )
                if spec is not None:
                    active_spec = spec
                    if tenant_id or policy is not None:
                        ctx = TenantContext(tenant_id=tenant_id) if tenant_id else None
                        active_spec = apply_security_policy(
                            spec,
                            context=ctx,
                            policy=SecurityPolicy(**policy)
                            if isinstance(policy, dict)
                            else policy,
                        )
                    result_data = conn.execute(
                        active_spec, statement_timeout_ms=timeout_ms
                    )
                else:
                    assert sql is not None
                    params = body.get("params", [])
                    cols, rows, latency = conn.execute_raw(sql, params)
                    result_data = {
                        "sql": sql,
                        "params": params,
                        "columns": cols,
                        "rows": rows,
                        "count": len(rows),
                        "limit": len(rows),
                        "offset": 0,
                        "latency_ms": round(latency, 2),
                        "dialect": conn.dialect_name,
                    }

                columns = result_data.get("columns", [])
                rows = result_data.get("rows", [])
                total_count = len(rows)

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header(
                    "Access-Control-Allow-Headers", "Content-Type, Authorization"
                )
                self.end_headers()

                def send_event(event_name: str, payload: dict[str, Any]) -> None:
                    chunk = f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n".encode()
                    self.wfile.write(chunk)
                    self.wfile.flush()

                send_event(
                    "metadata",
                    {
                        "columns": columns,
                        "total_estimated": total_count,
                        "dialect": result_data.get("dialect", connector_name),
                        "sql": result_data.get("sql", ""),
                    },
                )

                for i in range(0, total_count, batch_size):
                    batch_rows = rows[i : i + batch_size]
                    send_event(
                        "batch",
                        {
                            "rows": batch_rows,
                            "batch_index": i // batch_size,
                            "batch_size": len(batch_rows),
                        },
                    )

                send_event(
                    "stats",
                    {
                        "elapsed_ms": result_data.get("latency_ms", 0.0),
                        "rows_received": total_count,
                        "cache_hit": False,
                    },
                )

                send_event("done", {"status": "complete"})
                self.close_connection = True

            except SecurityError as exc:
                self.send_error_response(str(exc), code="FORBIDDEN", status=403)
            except Exception as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Streaming failed: {exc}",
                    code="STREAM_ERROR",
                    status=400,
                )
            return

        if path in ("/api/v1/explain", "/api/query/explain"):
            spec = body.get("spec")
            raw_explain = body.get("raw_explain")
            connector_name = body.get("connector", "sqlite")
            dialect = body.get("dialect", connector_name)
            schema = body.get("schema")

            try:
                if raw_explain is not None:
                    node = normalize_explain_output(raw_explain, dialect=dialect)
                elif spec is not None:
                    node = estimate_plan_from_spec(spec, schema=schema)
                elif body.get("sql"):
                    sql = body["sql"]
                    config = body.get("config", {})
                    try:
                        conn = get_connector(
                            connector_name,
                            **(config if isinstance(config, dict) else {}),
                        )
                        explain_sql = (
                            f"EXPLAIN QUERY PLAN {sql}"
                            if "sqlite" in connector_name
                            else f"EXPLAIN {sql}"
                        )
                        _, rows, _ = conn.execute_raw(explain_sql)
                        node = normalize_explain_output(rows, dialect=dialect)
                    except Exception:  # noqa: BLE001
                        node = estimate_plan_from_spec(
                            {"table": "query", "columns": ["*"]}
                        )
                else:
                    self.send_error_response(
                        "Either 'spec', 'raw_explain', or 'sql' must be provided.",
                        code="BAD_REQUEST",
                        status=400,
                    )
                    return

                self.send_json_response(node.to_dict())
            except Exception as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Explain failed: {exc}",
                    code="EXPLAIN_ERROR",
                    status=400,
                )
            return

        if path == "/api/v1/export":
            format_name = body.get("format", "csv")
            try:
                if "rows" in body:
                    export_data: Any = body
                elif "spec" in body:
                    connector_name = body.get("connector", "sqlite")
                    config = body.get("config", {})
                    conn = get_connector(
                        connector_name,
                        **(config if isinstance(config, dict) else {}),
                    )
                    res = conn.execute(body["spec"])
                    export_data = {
                        "rows": res.get("rows", []),
                        "columns": res.get("columns", []),
                    }
                else:
                    export_data = body

                payload, mime_type, ext = export_dataset(
                    export_data, format=format_name
                )
                self.send_bytes_response(payload, mime_type, filename=f"export.{ext}")
            except (ExportError, Exception) as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Export failed: {exc}", code="EXPORT_ERROR", status=400
                )
            return

        if path == "/api/v1/templates":
            try:
                created = self.template_store.save(body)
                self.send_json_response(created.to_dict(), status=201)
            except (TemplateError, Exception) as exc:  # noqa: BLE001
                self.send_error_response(
                    f"Template creation failed: {exc}",
                    code="VALIDATION_ERROR",
                    status=400,
                )
            return

        self.send_error_response(
            f"Endpoint not found: {path}", code="NOT_FOUND", status=404
        )

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/v1/templates/"):
            template_id = path.split("/")[-1]
            tenant_id = query.get("tenant_id", [None])[0]
            try:
                deleted = self.template_store.delete(template_id, tenant_id=tenant_id)
                if deleted:
                    self.send_json_response({"deleted": True, "id": template_id})
                else:
                    self.send_error_response(
                        f"Template '{template_id}' not found.",
                        code="NOT_FOUND",
                        status=404,
                    )
            except SecurityError as exc:
                self.send_error_response(str(exc), code="FORBIDDEN", status=403)
            return

        self.send_error_response(
            f"Endpoint not found: {path}", code="NOT_FOUND", status=404
        )


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    telemetry_collector: TelemetryCollector | None = None,
    template_store: TemplateStore | None = None,
    pool: ConnectionPool | None = None,
) -> ThreadingHTTPServer:
    """Creates and returns configured ThreadingHTTPServer instance."""
    collector = (
        telemetry_collector if telemetry_collector is not None else TelemetryCollector()
    )
    store = template_store if template_store is not None else TemplateStore()

    class BoundQueryBuilderHandler(QueryBuilderHandler):
        telemetry_collector = collector
        template_store = store
        connection_pool = pool

    return ThreadingHTTPServer((host, port), BoundQueryBuilderHandler)
