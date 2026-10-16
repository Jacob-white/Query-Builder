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
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.cache import compute_cache_key, get_global_cache
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.connectors.registry import get_connector
from query_builder.dialects import DIALECTS
from query_builder.explain import estimate_plan_from_spec, normalize_explain_output
from query_builder.export import ExportError, export_dataset, stream_export_dataset
from query_builder.nlq import NlqError, NlqService, NlqValidationError
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.pool import (
    ConnectionPool,
    ConnectionPoolManager,
    QueryCancelledError,
    get_connection_pool_manager,
    mask_credentials,
)
from query_builder.security import SecurityError
from query_builder.server_security import (
    SecureRequestError,
    ServerSecurity,
    secure_request,
)
from query_builder.telemetry import TelemetryCollector
from query_builder.templates import TemplateError, TemplateStore


@dataclass(frozen=True)
class Request:
    """A parsed request handed to a route handler."""

    path: str
    query: dict[str, list[str]]
    body: Any


Handler = Callable[["QueryBuilderHandler", Request], None]


@dataclass(frozen=True)
class Route:
    """One HTTP endpoint: the single source for dispatch and the OpenAPI document.

    ``path`` is the documented path. ``aliases`` are extra exact paths served by the
    same handler (undocumented), and ``prefix`` additionally matches every path
    starting with it (used for ``/{id}`` style resources).
    """

    method: str
    path: str
    handler: Handler
    summary: str
    responses: tuple[tuple[str, str], ...]
    aliases: tuple[str, ...] = ()
    prefix: str | None = None

    def matches_prefix(self, path: str) -> bool:
        return self.prefix is not None and path.startswith(self.prefix)


def _openapi_components() -> dict[str, Any]:
    """Static component schemas shared by the OpenAPI document."""
    return {
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
                    "vector_search": {"$ref": "#/components/schemas/VectorSearchSpec"},
                    "hybrid_search": {"$ref": "#/components/schemas/HybridSearchSpec"},
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


def _policy_spec(body: dict[str, Any], spec: Any, schema: Any = None) -> Any:
    """``spec`` with the request's tenant context and policy applied.

    Unchanged when the request carries neither ``tenant_id`` nor ``policy``. Both come from the
    REQUEST: this server does not authenticate callers, so a caller can omit them or name any
    tenant (see docs/SECURE_DEPLOYMENT.md).
    """
    tenant_id = body.get("tenant_id")
    policy = body.get("policy")
    if not (tenant_id or policy is not None):
        return spec
    ctx = TenantContext(tenant_id=tenant_id) if tenant_id else None
    return apply_security_policy(
        spec,
        schema=schema,
        context=ctx,
        policy=SecurityPolicy(**policy) if isinstance(policy, dict) else policy,
    )


def _get_health(h: QueryBuilderHandler, req: Request) -> None:
    """GET /health."""
    h.send_json_response(
        {
            "status": "ok",
            "version": "1.0.0",
            "dialects": sorted(DIALECTS.keys()),
        }
    )


def _get_openapi(h: QueryBuilderHandler, req: Request) -> None:
    """GET /openapi.json."""
    h.send_json_response(generate_openapi_spec())


def _get_docs(h: QueryBuilderHandler, req: Request) -> None:
    """GET /docs."""
    html_bytes = serve_swagger_ui_html().encode("utf-8")
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(html_bytes)))
    h._send_cors_headers()
    h.end_headers()
    h.wfile.write(html_bytes)


def _get_telemetry(h: QueryBuilderHandler, req: Request) -> None:
    """GET /api/v1/telemetry."""
    h.send_json_response(h.telemetry_collector.get_metrics())


def _get_templates(h: QueryBuilderHandler, req: Request) -> None:
    """GET /api/v1/templates."""
    query = req.query
    tenant_id = query.get("tenant_id", [None])[0]
    category = query.get("category", [None])[0]
    search = query.get("search", [None])[0]
    templates = h.template_store.list(
        tenant_id=tenant_id, category=category, search=search
    )
    h.send_json_response([t.to_dict() for t in templates])


def _get_nlq_providers(h: QueryBuilderHandler, req: Request) -> None:
    """GET /api/v1/nlq/providers."""
    h.send_json_response({"providers": h.nlq_service.list_available_providers()})


def _get_connections(h: QueryBuilderHandler, req: Request) -> None:
    """GET /api/v1/connections."""
    h.send_json_response({"connections": h.connection_pool_manager.list_pools()})


def _post_introspect(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/introspect."""
    body = req.body
    connector_name = body.get("connector", "sqlite")
    config = body.get("config", {})
    try:
        conn = get_connector(
            connector_name, **(config if isinstance(config, dict) else {})
        )
        snapshot = conn.introspect_schema()
        h.send_json_response(snapshot)
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"Introspection failed: {exc}",
            code="INTROSPECTION_ERROR",
            status=400,
        )


def _post_compile(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/compile."""
    body = req.body
    spec = body.get("spec")
    if not spec or not isinstance(spec, dict):
        h.send_error_response(
            "Missing required 'spec' dictionary.",
            code="BAD_REQUEST",
            status=400,
        )
        return

    schema = body.get("schema")
    dialect = body.get("dialect", "postgres")

    try:
        active_spec = _policy_spec(body, spec, schema)

        compiler = QueryCompiler(active_spec, schema=schema, dialect=dialect)
        main_sql, params, count_sql, count_params = compiler.compile()
        h.send_json_response(
            {
                "sql": main_sql,
                "params": params,
                "count_sql": count_sql,
                "count_params": count_params,
                "dialect": dialect,
            }
        )
    except SecurityError as exc:
        h.send_error_response(str(exc), code="FORBIDDEN", status=403)
    except (CompilationError, Exception) as exc:  # noqa: BLE001
        h.send_error_response(
            f"Compilation failed: {exc}",
            code="COMPILATION_ERROR",
            status=400,
        )


def _post_validate(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/validate."""
    body = req.body
    sql = body.get("sql")
    if not sql or not isinstance(sql, str):
        h.send_error_response(
            "Missing required 'sql' string.",
            code="BAD_REQUEST",
            status=400,
        )
        return

    allowed_schemas = body.get("allowed_schemas")
    try:
        result = validate_sql_ast(sql, allowed_schemas=allowed_schemas)
        h.send_json_response(result)
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"Validation failed: {exc}",
            code="VALIDATION_ERROR",
            status=400,
        )


def _post_execute(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/execute, /api/v1/query/execute, /api/query."""
    body = req.body
    spec = body.get("spec") or body.get("query")
    sql = body.get("sql")
    connector_name = body.get("connector", body.get("dialect", "sqlite"))
    connection_id = body.get("connection_id")
    config = body.get("config", {})
    tenant_id = body.get("tenant_id")
    timeout_ms = body.get("timeout_ms")
    use_cache = body.get("use_cache", False)
    cache_ttl = body.get("cache_ttl")
    execution_id = body.get("execution_id")
    limit = body.get("limit")
    offset = body.get("offset")

    if not spec and not sql:
        h.send_error_response(
            "Either 'spec', 'query', or 'sql' must be provided.",
            code="BAD_REQUEST",
            status=400,
        )
        return

    if spec is None:
        pol = body.get("policy") or (
            h.server_security.policy if h.server_security else None
        )
        tenant_active = bool(
            (isinstance(pol, dict) and pol.get("enforce_tenant_isolation"))
            or (isinstance(pol, SecurityPolicy) and pol.enforce_tenant_isolation)
        )
        if tenant_active:
            h.send_error_response(
                "Raw SQL execution is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
                code="FORBIDDEN",
                status=403,
            )
            return

        val_res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
        if not val_res.get("valid") or not val_res.get("is_read_only"):
            violations = val_res.get(
                "violations", ["Query failed AST safety validation."]
            )
            h.send_error_response(
                f"Security violation: {'; '.join(violations)}",
                code="FORBIDDEN",
                status=403,
            )
            return

    eid, token = h.connection_pool_manager.create_execution(execution_id)

    cache = get_global_cache()
    cache_key = None
    if use_cache:
        target = (
            spec if spec is not None else {"sql": sql, "params": body.get("params", [])}
        )
        cache_key = compute_cache_key(
            target, dialect=connector_name, tenant_id=tenant_id
        )
        cached_res = cache.get(cache_key)
        if cached_res is not None and isinstance(cached_res, dict):
            res_copy = dict(cached_res)
            res_copy["cached"] = True
            h.connection_pool_manager.unregister_execution(eid)
            h.send_json_response(res_copy)
            return

    try:
        token.throw_if_cancelled()

        # If connection_id is provided and registered in connection_pool_manager
        if connection_id and h.connection_pool_manager.has_pool(connection_id):
            result_data = h.connection_pool_manager.execute_query(
                sql_or_spec=_policy_spec(body, spec) if spec is not None else sql,
                connection_id=connection_id,
                params=body.get("params"),
                timeout_ms=timeout_ms,
                limit=limit,
                offset=offset,
                execution_id=eid,
                cancellation_token=token,
            )
            executed_sql = result_data.get("sql", "")
        else:
            conn = get_connector(
                connector_name,
                **(config if isinstance(config, dict) else {}),
            )

            if spec is not None:
                active_spec = _policy_spec(body, spec)
                token.throw_if_cancelled()
                result_data = conn.execute(active_spec, statement_timeout_ms=timeout_ms)
                token.throw_if_cancelled()
                executed_sql = result_data.get("sql", "")
            else:
                params = body.get("params", [])
                token.throw_if_cancelled()
                cols, rows, latency = conn.execute_raw(sql, params)
                token.throw_if_cancelled()
                result_data = {
                    "sql": sql,
                    "params": params,
                    "columns": cols,
                    "rows": rows,
                    "count": len(rows),
                    "limit": limit or len(rows),
                    "offset": offset or 0,
                    "latency_ms": round(latency, 2),
                    "dialect": conn.dialect_name,
                }
                executed_sql = sql

        result_data["execution_id"] = eid
        result_data["cached"] = False
        if use_cache and cache_key is not None:
            cache.set(cache_key, result_data, ttl=cache_ttl)

        h.telemetry_collector.record_execution(
            sql=executed_sql,
            latency_ms=result_data.get("latency_ms", 0.0),
            row_count=result_data.get("count", len(result_data.get("rows", []))),
            status="success",
            dialect=result_data.get("dialect", "sqlite"),
            tenant_id=tenant_id,
        )
        h.send_json_response(result_data)
    except QueryCancelledError as exc:
        h.send_error_response(str(exc), code="CANCELLED", status=400)
    except SecurityError as exc:
        h.send_error_response(str(exc), code="FORBIDDEN", status=403)
    except Exception as exc:  # noqa: BLE001
        h.telemetry_collector.record_execution(
            sql=sql or str(spec),
            latency_ms=0.0,
            status="error",
            error_message=str(exc),
            tenant_id=tenant_id,
        )
        h.send_error_response(
            f"Execution failed: {exc}",
            code="EXECUTION_ERROR",
            status=400,
        )
    finally:
        h.connection_pool_manager.unregister_execution(eid)


def register_connection(
    manager: ConnectionPoolManager,
    connection_id: str,
    connector_name: str,
    config: dict[str, Any],
    *,
    dialect: str | None = None,
    max_size: int = 10,
    min_size: int = 0,
    timeout: float = 30.0,
    metadata: dict[str, Any] | None = None,
) -> ConnectionPool:
    """Register a pooled connection under ``connection_id`` (what ``POST /api/v1/connections``
    does). Operators use it to set up the connections secure mode serves."""
    meta = dict(metadata or {})
    meta["connector"] = connector_name
    meta["dialect"] = dialect or meta.get("dialect") or connector_name

    def factory() -> Any:
        return get_connector(connector_name, **config).connect()

    pool = ConnectionPool(
        factory=factory, max_size=max_size, min_size=min_size, timeout=timeout
    )
    manager.register_pool(connection_id, pool, metadata=meta)
    return pool


def _post_connections(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/connections."""
    body = req.body
    conn_id = body.get("connection_id")
    if not conn_id or not isinstance(conn_id, str):
        h.send_error_response(
            "Missing required 'connection_id'.", code="BAD_REQUEST", status=400
        )
        return

    connector_name = body.get("connector", "sqlite")
    config = body.get("config", {})
    max_size = body.get("max_size", 10)
    min_size = body.get("min_size", 0)
    timeout = body.get("timeout", 30.0)
    metadata = dict(body.get("metadata", {}))
    metadata["connector"] = connector_name
    metadata["dialect"] = body.get("dialect", connector_name)

    try:
        register_connection(
            h.connection_pool_manager,
            conn_id,
            connector_name,
            config if isinstance(config, dict) else {},
            dialect=metadata["dialect"],
            max_size=int(max_size),
            min_size=int(min_size),
            timeout=float(timeout),
            metadata=metadata,
        )
        h.send_json_response(
            {
                "status": "registered",
                "connection_id": conn_id,
                "metadata": mask_credentials(metadata),
            },
            status=201,
        )
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"Failed to register connection pool: {exc}",
            code="POOL_ERROR",
            status=400,
        )


def _post_connections_test(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/connections/test."""
    body = req.body
    target = body.get("connection_id") or body
    try:
        res = h.connection_pool_manager.test_connection(target)
        h.send_json_response(res)
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"Connection test failed: {exc}",
            code="CONNECTION_TEST_ERROR",
            status=400,
        )


def _post_connections_cancel(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/connections/cancel."""
    body = req.body
    exec_id = body.get("execution_id")
    if not exec_id or not isinstance(exec_id, str):
        h.send_error_response(
            "Missing required 'execution_id'.", code="BAD_REQUEST", status=400
        )
        return
    cancelled = h.connection_pool_manager.cancel_execution(exec_id)
    h.send_json_response(
        {
            "cancelled": cancelled,
            "execution_id": exec_id,
            "message": "Execution cancelled"
            if cancelled
            else "Execution not found or already completed",
        }
    )


def _post_stream(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/stream, /api/query/stream (Server-Sent Events)."""
    body = req.body
    spec = body.get("spec")
    sql = body.get("sql")
    connector_name = body.get("connector", "sqlite")
    config = body.get("config", {})
    timeout_ms = body.get("timeout_ms")
    batch_size = int(body.get("batch_size", 250))
    if batch_size <= 0:
        batch_size = 250

    if not spec and not sql:
        h.send_error_response(
            "Either 'spec' or 'sql' must be provided.",
            code="BAD_REQUEST",
            status=400,
        )
        return

    if spec is None:
        pol = body.get("policy")
        tenant_active = bool(
            (isinstance(pol, dict) and pol.get("enforce_tenant_isolation"))
            or (isinstance(pol, SecurityPolicy) and pol.enforce_tenant_isolation)
        )
        if tenant_active:
            h.send_error_response(
                "Raw SQL execution is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
                code="FORBIDDEN",
                status=403,
            )
            return

        val_res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
        if not val_res.get("valid") or not val_res.get("is_read_only"):
            violations = val_res.get(
                "violations", ["Query failed AST safety validation."]
            )
            h.send_error_response(
                f"Security violation: {'; '.join(violations)}",
                code="FORBIDDEN",
                status=403,
            )
            return

    try:
        conn = get_connector(
            connector_name,
            **(config if isinstance(config, dict) else {}),
        )
        if spec is not None:
            active_spec = _policy_spec(body, spec)
            result_data = conn.execute(active_spec, statement_timeout_ms=timeout_ms)
        else:
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

        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Connection", "keep-alive")
        h.send_header("Access-Control-Allow-Origin", "*")
        h.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        h.end_headers()

        def send_event(event_name: str, payload: dict[str, Any]) -> None:
            chunk = f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n".encode()
            h.wfile.write(chunk)
            h.wfile.flush()

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
        h.close_connection = True

    except SecurityError as exc:
        h.send_error_response(str(exc), code="FORBIDDEN", status=403)
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"Streaming failed: {exc}",
            code="STREAM_ERROR",
            status=400,
        )


def _post_explain(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/explain, /api/query/explain."""
    body = req.body
    spec = body.get("spec") or body.get("query")
    raw_explain = body.get("raw_explain")
    connector_name = body.get("connector", "sqlite")
    dialect = body.get("dialect", connector_name)
    schema = body.get("schema")

    try:
        if raw_explain is not None:
            node = normalize_explain_output(raw_explain, dialect=dialect)
        elif spec is not None:
            active_spec = _policy_spec(body, spec, schema)
            node = estimate_plan_from_spec(active_spec, schema=schema)
        elif body.get("sql"):
            sql = body["sql"]
            pol = body.get("policy") or (
                h.server_security.policy if h.server_security else None
            )
            tenant_active = bool(
                (isinstance(pol, dict) and pol.get("enforce_tenant_isolation"))
                or (isinstance(pol, SecurityPolicy) and pol.enforce_tenant_isolation)
            )
            if tenant_active:
                h.send_error_response(
                    "Raw SQL execution is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
                    code="FORBIDDEN",
                    status=403,
                )
                return

            val_res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                h.send_error_response(
                    f"Security violation: {'; '.join(violations)}",
                    code="FORBIDDEN",
                    status=403,
                )
                return

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
                node = estimate_plan_from_spec({"table": "query", "columns": ["*"]})
        else:
            h.send_error_response(
                "Either 'spec', 'raw_explain', or 'sql' must be provided.",
                code="BAD_REQUEST",
                status=400,
            )
            return

        h.send_json_response(node.to_dict())
    except SecurityError as exc:
        h.send_error_response(str(exc), code="FORBIDDEN", status=403)
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"Explain failed: {exc}",
            code="EXPLAIN_ERROR",
            status=400,
        )


def _post_export(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/export."""
    body = req.body
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
            res = conn.execute(_policy_spec(body, body["spec"]))
            export_data = {
                "rows": res.get("rows", []),
                "columns": res.get("columns", []),
            }
        else:
            export_data = body

        payload, mime_type, ext = export_dataset(export_data, format=format_name)
        h.send_bytes_response(payload, mime_type, filename=f"export.{ext}")
    except (ExportError, Exception) as exc:  # noqa: BLE001
        h.send_error_response(f"Export failed: {exc}", code="EXPORT_ERROR", status=400)


def _post_export_stream(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/export/stream (chunked transfer)."""
    body = req.body
    format_name = body.get("format", "csv")
    chunk_size = int(body.get("chunk_size", 1000))
    if chunk_size <= 0:
        chunk_size = 1000

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
            res = conn.execute(_policy_spec(body, body["spec"]))
            export_data = {
                "rows": res.get("rows", []),
                "columns": res.get("columns", []),
            }
        elif "sql" in body:
            raw_sql = body["sql"]
            pol = body.get("policy")
            tenant_active = bool(
                (isinstance(pol, dict) and pol.get("enforce_tenant_isolation"))
                or (isinstance(pol, SecurityPolicy) and pol.enforce_tenant_isolation)
            )
            if tenant_active:
                h.send_error_response(
                    "Raw SQL execution is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
                    code="FORBIDDEN",
                    status=403,
                )
                return

            val_res = validate_sql_ast(
                raw_sql, allowed_schemas=body.get("allowed_schemas")
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                h.send_error_response(
                    f"Security violation: {'; '.join(violations)}",
                    code="FORBIDDEN",
                    status=403,
                )
                return

            connector_name = body.get("connector", "sqlite")
            config = body.get("config", {})
            conn = get_connector(
                connector_name,
                **(config if isinstance(config, dict) else {}),
            )
            cols, rows, _ = conn.execute_raw(raw_sql, body.get("params", []))
            export_data = {
                "rows": rows,
                "columns": cols,
            }
        else:
            export_data = body

        stream_iter, mime_type, ext = stream_export_dataset(
            export_data, format=format_name, chunk_size=chunk_size
        )

        h.send_response(200)
        h.send_header("Content-Type", mime_type)
        h.send_header("Transfer-Encoding", "chunked")
        h.send_header("Content-Disposition", f'attachment; filename="export.{ext}"')
        h.send_header("Access-Control-Allow-Origin", "*")
        h.send_header("Access-Control-Expose-Headers", "Content-Disposition")
        h.end_headers()

        for chunk in stream_iter:
            h.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
            h.wfile.flush()
        h.wfile.write(b"0\r\n\r\n")
        h.wfile.flush()
        h.close_connection = True
    except (ExportError, Exception) as exc:  # noqa: BLE001
        h.send_error_response(
            f"Streaming export failed: {exc}",
            code="EXPORT_ERROR",
            status=400,
        )


def _post_templates(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/templates."""
    body = req.body
    try:
        created = h.template_store.save(body)
        h.send_json_response(created.to_dict(), status=201)
    except (TemplateError, Exception) as exc:  # noqa: BLE001
        h.send_error_response(
            f"Template creation failed: {exc}",
            code="VALIDATION_ERROR",
            status=400,
        )


def _post_nlq_translate(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/nlq/translate."""
    body = req.body
    prompt = body.get("prompt")
    if not prompt or not isinstance(prompt, str) or not prompt.strip():
        h.send_error_response(
            "Missing required non-empty 'prompt' string.",
            code="BAD_REQUEST",
            status=400,
        )
        return
    try:
        result = h.nlq_service.translate(body)
        h.send_json_response(result.to_dict())
    except (NlqValidationError, NlqError) as exc:
        h.send_error_response(
            f"NLQ translation failed: {exc}",
            code="NLQ_ERROR",
            status=400,
        )
    except Exception as exc:  # noqa: BLE001
        h.send_error_response(
            f"NLQ internal error: {exc}",
            code="INTERNAL_ERROR",
            status=500,
        )


def _post_nlq_explain(h: QueryBuilderHandler, req: Request) -> None:
    """POST /api/v1/nlq/explain."""
    body = req.body
    query = body.get("query", body.get("spec"))
    if not query or not isinstance(query, dict):
        h.send_error_response(
            "Missing required 'query' or 'spec' dictionary.",
            code="BAD_REQUEST",
            status=400,
        )
        return
    dialect = body.get("dialect", "postgres")
    provider = body.get("provider", "mock")
    api_key = body.get("api_key")
    model = body.get("model")
    try:
        res = h.nlq_service.explain(
            query,
            dialect=dialect,
            provider=provider,
            api_key=api_key,
            model=model,
        )
        h.send_json_response(res.to_dict())
    except (NlqError, Exception) as exc:  # noqa: BLE001
        h.send_error_response(
            f"NLQ explain failed: {exc}",
            code="NLQ_ERROR",
            status=400,
        )


def _delete_template(h: QueryBuilderHandler, req: Request) -> None:
    """DELETE /api/v1/templates/{id}."""
    path = req.path
    query = req.query
    template_id = path.split("/")[-1]
    tenant_id = query.get("tenant_id", [None])[0]
    try:
        deleted = h.template_store.delete(template_id, tenant_id=tenant_id)
        if deleted:
            h.send_json_response({"deleted": True, "id": template_id})
        else:
            h.send_error_response(
                f"Template '{template_id}' not found.",
                code="NOT_FOUND",
                status=404,
            )
    except SecurityError as exc:
        h.send_error_response(str(exc), code="FORBIDDEN", status=403)


def _delete_connection(h: QueryBuilderHandler, req: Request) -> None:
    """DELETE /api/v1/connections[/{id}]."""
    path = req.path
    query = req.query
    conn_id = query.get("connection_id", [None])[0]
    if not conn_id and path.startswith("/api/v1/connections/"):
        conn_id = path.split("/")[-1]
    if not conn_id:
        h.send_error_response(
            "Missing required 'connection_id'.",
            code="BAD_REQUEST",
            status=400,
        )
        return
    if h.connection_pool_manager.has_pool(conn_id):
        h.connection_pool_manager.remove_pool(conn_id)
        h.send_json_response({"deleted": True, "connection_id": conn_id})
    else:
        h.send_error_response(
            f"Connection pool '{conn_id}' not found.",
            code="NOT_FOUND",
            status=404,
        )


ROUTES: tuple[Route, ...] = (
    Route(
        "GET",
        "/health",
        _get_health,
        "Health Check",
        (("200", "Server health status"),),
    ),
    Route(
        "GET",
        "/openapi.json",
        _get_openapi,
        "OpenAPI Specification",
        (("200", "OpenAPI 3.1 document"),),
    ),
    Route(
        "GET",
        "/docs",
        _get_docs,
        "Swagger UI Documentation",
        (("200", "Swagger UI HTML"),),
    ),
    Route(
        "POST",
        "/api/v1/introspect",
        _post_introspect,
        "Introspect Database Schema",
        (("200", "Schema snapshot"), ("400", "Introspection error")),
    ),
    Route(
        "POST",
        "/api/v1/compile",
        _post_compile,
        "Compile Query Specification",
        (
            ("200", "Compiled SQL and parameters"),
            ("400", "Compilation error"),
            ("403", "Forbidden by security policy"),
        ),
    ),
    Route(
        "POST",
        "/api/v1/validate",
        _post_validate,
        "Validate SQL AST",
        (("200", "Validation result"), ("400", "Validation error")),
    ),
    Route(
        "POST",
        "/api/v1/execute",
        _post_execute,
        "Execute Query",
        (
            ("200", "Query result"),
            ("400", "Execution error"),
            ("403", "Forbidden by security policy"),
        ),
        aliases=("/api/query",),
    ),
    Route(
        "POST",
        "/api/v1/query/execute",
        _post_execute,
        "Execute Live Query with Connection Pool",
        (
            ("200", "Live query execution result"),
            ("400", "Execution error or cancellation"),
        ),
    ),
    Route(
        "GET",
        "/api/v1/connections",
        _get_connections,
        "List Registered Connection Pools",
        (("200", "List of connection pools"),),
    ),
    Route(
        "POST",
        "/api/v1/connections",
        _post_connections,
        "Register New Connection Pool",
        (("201", "Connection pool registered"),),
    ),
    Route(
        "DELETE",
        "/api/v1/connections",
        _delete_connection,
        "Remove Connection Pool",
        (("200", "Connection pool removed"),),
        prefix="/api/v1/connections/",
    ),
    Route(
        "POST",
        "/api/v1/connections/test",
        _post_connections_test,
        "Test Connection Health & Latency",
        (("200", "Connection test result"),),
    ),
    Route(
        "POST",
        "/api/v1/connections/cancel",
        _post_connections_cancel,
        "Cancel In-Flight Query Execution",
        (("200", "Cancellation result"),),
    ),
    Route(
        "POST",
        "/api/v1/stream",
        _post_stream,
        "Stream Query Execution via Server-Sent Events",
        (
            ("200", "Server-Sent Events stream"),
            ("400", "Streaming error"),
            ("403", "Forbidden by security policy"),
        ),
        aliases=("/api/query/stream",),
    ),
    Route(
        "POST",
        "/api/v1/explain",
        _post_explain,
        "Explain and Analyze Query Plan",
        (("200", "Normalized QueryPlanNode tree"), ("400", "Explain error")),
        aliases=("/api/query/explain",),
    ),
    Route(
        "POST",
        "/api/v1/export",
        _post_export,
        "Export Tabular Data",
        (("200", "Exported tabular file"), ("400", "Export error")),
    ),
    Route(
        "POST",
        "/api/v1/export/stream",
        _post_export_stream,
        "Stream Tabular Data Export with Chunked Transfer Encoding",
        (
            ("200", "Chunked binary/text stream download"),
            ("400", "Streaming export error"),
        ),
    ),
    Route(
        "GET",
        "/api/v1/templates",
        _get_templates,
        "List Templates",
        (("200", "List of templates"),),
    ),
    Route(
        "POST",
        "/api/v1/templates",
        _post_templates,
        "Create or Update Template",
        (("201", "Created template"), ("400", "Validation error")),
    ),
    Route(
        "DELETE",
        "/api/v1/templates/{id}",
        _delete_template,
        "Delete Template",
        (("200", "Deletion confirmation"), ("403", "Forbidden"), ("404", "Not found")),
        prefix="/api/v1/templates/",
    ),
    Route(
        "GET",
        "/api/v1/telemetry",
        _get_telemetry,
        "Get Execution Telemetry Metrics",
        (("200", "Telemetry metrics summary"),),
    ),
    Route(
        "POST",
        "/api/v1/nlq/translate",
        _post_nlq_translate,
        "Translate Natural Language into QuerySpec AST",
        (("200", "Validated QuerySpec and confidence"), ("400", "Translation error")),
    ),
    Route(
        "POST",
        "/api/v1/nlq/explain",
        _post_nlq_explain,
        "Explain Visual Query AST in Natural Language",
        (("200", "Natural language explanation"), ("400", "Explain error")),
    ),
    Route(
        "GET",
        "/api/v1/nlq/providers",
        _get_nlq_providers,
        "List Available NLQ Providers",
        (("200", "List of available NLQ providers"),),
    ),
)

_EXACT_ROUTES: dict[tuple[str, str], Route] = {}
for _route in ROUTES:
    for _p in (_route.path, *_route.aliases):
        _EXACT_ROUTES.setdefault((_route.method, _p), _route)


def find_route(method: str, path: str) -> Route | None:
    """Resolves the route serving ``method`` + ``path`` (exact first, then prefix)."""
    route = _EXACT_ROUTES.get((method, path))
    if route is not None:
        return route
    for candidate in ROUTES:
        if candidate.method == method and candidate.matches_prefix(path):
            return candidate
    return None


def generate_openapi_spec() -> dict[str, Any]:
    """Generates the OpenAPI 3.1.0 JSON specification document from ``ROUTES``."""
    paths: dict[str, dict[str, Any]] = {}
    for route in ROUTES:
        paths.setdefault(route.path, {})[route.method.lower()] = {
            "summary": route.summary,
            "responses": {
                code: {"description": text} for code, text in route.responses
            },
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Query Builder API",
            "version": "1.0.0",
            "description": "Universal SQL Query Builder, Declarative Compiler, and AST Safety Microservice.",
        },
        "paths": paths,
        "components": _openapi_components(),
    }


class QueryBuilderHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Query-Builder microservice API."""

    telemetry_collector: TelemetryCollector = TelemetryCollector()
    template_store: TemplateStore = TemplateStore()
    connection_pool: ConnectionPool | None = None
    connection_pool_manager: ConnectionPoolManager = get_connection_pool_manager()
    nlq_service: NlqService = NlqService()
    #: secure mode settings (``None`` = the default, request-trusting mode)
    server_security: ServerSecurity | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr HTTP request logging for test cleanliness."""

    def _send_cors_headers(self) -> None:
        secure = self.server_security
        if secure is not None:
            # secure mode: no wildcard; only listed origins may call from a browser
            origin = secure.cors_origin_for(self.headers.get("Origin"))
            if origin is None:
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
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

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query: dict[str, list[str]] = {}
        body: Any = {}
        if method == "POST":
            try:
                body = self.parse_json_body()
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self.send_error_response(
                    f"Invalid JSON request body: {exc}",
                    code="BAD_REQUEST",
                    status=400,
                )
                return
        else:
            query = urllib.parse.parse_qs(parsed.query)

        secure = self.server_security
        if secure is not None:
            try:
                body = secure_request(
                    secure,
                    method,
                    path,
                    dict(self.headers.items()),
                    body,
                    self.connection_pool_manager.has_pool,
                )
            except SecureRequestError as exc:
                self.send_error_response(exc.message, code=exc.code, status=exc.status)
                return

        route = find_route(method, path)
        if route is None:
            self.send_error_response(
                f"Endpoint not found: {path}", code="NOT_FOUND", status=404
            )
            return
        route.handler(self, Request(path=path, query=query, body=body))

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    telemetry_collector: TelemetryCollector | None = None,
    template_store: TemplateStore | None = None,
    pool: ConnectionPool | None = None,
    connection_pool_manager: ConnectionPoolManager | None = None,
    nlq_service: NlqService | None = None,
    security: ServerSecurity | None = None,
) -> ThreadingHTTPServer:
    """Creates and returns configured ThreadingHTTPServer instance.

    ``security`` turns on secure mode (see ``query_builder.server_security``): the server, not
    the client, chooses tenant, policy and connection. Without it the server trusts the request.
    """
    collector = (
        telemetry_collector if telemetry_collector is not None else TelemetryCollector()
    )
    store = template_store if template_store is not None else TemplateStore()
    nlq = nlq_service if nlq_service is not None else NlqService()
    mgr = (
        connection_pool_manager
        if connection_pool_manager is not None
        else get_connection_pool_manager()
    )
    if pool is not None:
        mgr.register_pool("default", pool)

    class BoundQueryBuilderHandler(QueryBuilderHandler):
        server_security = security
        telemetry_collector = collector
        template_store = store
        connection_pool = pool
        connection_pool_manager = mgr
        nlq_service = nlq

    return ThreadingHTTPServer((host, port), BoundQueryBuilderHandler)
