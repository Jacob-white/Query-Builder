"""
Litestar Router Integration for Query-Builder.
==============================================
Turnkey production-ready Litestar Router factory registering:
- GET  /capabilities (and /v1/capabilities): Retrieve active EngineCapabilities
- GET  /schema       (and /v1/schema, /introspect): Introspect database schema snapshot
- POST /compile      (and /v1/compile): Compile declarative QuerySpec to target dialect SQL
- POST /validate     (and /v1/validate): Validate arbitrary SQL AST safety
- POST /execute      (and /v1/execute): Execute query specification or raw SQL against connector
- POST /export       (and /v1/export): Multi-format export (CSV, JSON, JSONL, Arrow, Parquet, Excel)
- POST /export/stream (and /v1/export/stream): Chunked streaming export
- POST /explain      (and /v1/explain): Execution plan estimation and performance advisory
- POST /join-path    (and /v1/join-path): Shortest relational join path solver
- POST /nlq          (and /v1/nlq, /nlq/translate, /v1/nlq/translate): Natural language to QuerySpec
- POST /nlq/explain  (and /v1/nlq/explain): Plain-English query explanation
- GET  /nlq/providers (and /v1/nlq/providers): List registered NLQ providers
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from typing import Any

from query_builder.advisor import analyze_query_performance, recommend_indexes
from query_builder.ast_validator import validate_sql_ast
from query_builder.capabilities import (
    DisabledFeatureError,
    EngineCapabilities,
    disabled_feature_message,
)
from query_builder.compiler import QueryCompiler
from query_builder.explain import estimate_plan_from_spec
from query_builder.export import ExportError, export_dataset, stream_export_dataset
from query_builder.integrations._errors import public_error
from query_builder.integrations.django import (
    _exec_conn_method,
    _filter_schema_tables,
    _get_effective_policy,
    _normalize_schema_snapshot,
    _resolve_conn,
    _resolve_tenant_sync,
    _unauthorized_message,
)
from query_builder.join_solver import find_join_path
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.security import SecurityError


def _get_litestar() -> tuple[Any, Any, Any, Any, Any]:
    """Lazily imports Litestar components `(Router, Response, Stream, get, post)`."""
    try:
        ls = importlib.import_module("litestar")
        if ls is None:
            raise ImportError("Litestar is not installed")
        stream_cls = getattr(
            getattr(ls, "response", ls), "Stream", getattr(ls, "Response", None)
        )
        return ls.Router, ls.Response, stream_cls, ls.get, ls.post
    except ImportError as exc:
        raise ImportError(
            "Litestar is not installed. Install via 'pip install litestar' to use create_litestar_router."
        ) from exc


def create_litestar_router(
    connector: Any,
    *,
    security: SecurityPolicy | dict[str, Any] | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    tenant_resolver: Callable[[Any], TenantContext | dict[str, Any] | str | None]
    | None = None,
    path: str = "/",
    tags: list[str] | None = None,
    schema_cache_ttl: float = 300.0,
    max_rows: int | None = None,
    statement_timeout_ms: int | None = None,
    allow_raw_sql: bool = True,
    ai_provider: Any = None,
    nlq_service: Any = None,
) -> Any:
    """Creates and returns a configured Litestar Router for Query-Builder."""
    Router, Response, Stream, get, post = _get_litestar()

    policy = _get_effective_policy(security, tenant_resolver is not None)
    effective_capabilities: EngineCapabilities = (
        capabilities
        if isinstance(capabilities, EngineCapabilities)
        else (
            EngineCapabilities.from_dict(capabilities)
            if isinstance(capabilities, dict)
            else EngineCapabilities.default()
        )
    )

    cached_schema_data: dict[str, Any] | None = None
    cached_schema_time: float = 0.0

    def _json_resp(payload: Any, status_code: int = 200) -> Any:
        return Response(
            content=payload,
            status_code=status_code,
            media_type="application/json",
        )

    def _is_tenant_active(tenant_ctx: TenantContext | None) -> bool:
        return bool(
            tenant_ctx is not None
            or tenant_resolver is not None
            or (policy is not None and policy.enforce_tenant_isolation)
        )

    @get(path=["/capabilities", "/v1/capabilities"])
    async def get_capabilities() -> Any:
        return _json_resp({"capabilities": effective_capabilities.to_dict()})

    @get(path=["/schema", "/v1/schema", "/introspect"])
    async def get_schema(request: Any = None, refresh: bool = False) -> Any:
        nonlocal cached_schema_data, cached_schema_time
        is_refresh = bool(refresh)
        if not is_refresh and request is not None:
            qp = getattr(request, "query_params", {}) or {}
            is_refresh = str(qp.get("refresh", "")).lower() in ("true", "1")

        if (
            not is_refresh
            and schema_cache_ttl > 0.0
            and cached_schema_data is not None
            and (time.monotonic() - cached_schema_time) < schema_cache_ttl
        ):
            return _json_resp(cached_schema_data)

        conn = _resolve_conn(connector)
        try:
            snapshot = _exec_conn_method(conn, "introspect_schema")
            data = _normalize_schema_snapshot(snapshot)
            data["capabilities"] = effective_capabilities.to_dict()
            data = _filter_schema_tables(data, policy)
            if schema_cache_ttl > 0.0:
                cached_schema_data = dict(data)
                cached_schema_time = time.monotonic()
            return _json_resp(data)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Schema introspection failed", exc)},
                status_code=500,
            )

    @post(path=["/compile", "/v1/compile"])
    async def compile_query(data: dict[str, Any], request: Any = None) -> Any:
        conn = _resolve_conn(connector)
        try:
            body = data if isinstance(data, dict) else {}
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = body.get("spec")
            if not spec or not isinstance(spec, dict):
                return _json_resp({"error": "Missing required 'spec'"}, status_code=400)

            active_spec = spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    spec,
                    schema=body.get("schema"),
                    context=tenant_ctx,
                    policy=policy,
                )

            dialect = body.get("dialect") or getattr(conn, "dialect_name", "postgres")
            compiler = QueryCompiler(
                active_spec,
                schema=body.get("schema"),
                dialect=dialect,
                capabilities=effective_capabilities,
            )
            main_sql, params, count_sql, count_params = compiler.compile()
            val_res = validate_sql_ast(main_sql, dialect=dialect)
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                return _json_resp(
                    {"error": f"Security violation: {'; '.join(violations)}"},
                    status_code=403,
                )
            return _json_resp(
                {
                    "sql": main_sql,
                    "params": params,
                    "count_sql": count_sql,
                    "count_params": count_params,
                    "dialect": dialect,
                }
            )
        except PermissionError as exc:
            return _json_resp({"error": _unauthorized_message(exc)}, status_code=401)
        except DisabledFeatureError as exc:
            return _json_resp(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status_code=403,
            )
        except SecurityError as exc:
            return _json_resp({"error": str(exc)}, status_code=403)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Compilation failed", exc)}, status_code=400
            )

    @post(path=["/validate", "/v1/validate"])
    async def validate_query(data: dict[str, Any]) -> Any:
        try:
            body = data if isinstance(data, dict) else {}
            sql = body.get("sql")
            if not sql or not isinstance(sql, str):
                return _json_resp({"error": "Missing required 'sql'"}, status_code=400)
            res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
            return _json_resp(res)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Validation failed", exc)}, status_code=400
            )

    @post(path=["/execute", "/v1/execute"])
    async def execute_query(data: dict[str, Any], request: Any = None) -> Any:
        conn = _resolve_conn(connector)
        try:
            body = data if isinstance(data, dict) else {}
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = body.get("spec") or body.get("query")
            sql = body.get("sql")
            if not spec and not sql:
                return _json_resp(
                    {"error": "Either 'spec' or 'sql' must be provided"},
                    status_code=400,
                )

            eff_timeout = body.get("timeout_ms") or statement_timeout_ms

            if spec is not None:
                if spec.get("ctes"):
                    effective_capabilities.require_feature("ctes")
                if spec.get("window_functions"):
                    effective_capabilities.require_feature("window_functions")
                if (
                    spec.get("rollup")
                    or spec.get("cube")
                    or spec.get("grouping_sets")
                    or spec.get("pivot")
                ):
                    effective_capabilities.require_feature("analytical_grouping")
                if spec.get("vector_search") or spec.get("hybrid_search"):
                    effective_capabilities.require_feature("vector_search")

                active_spec = dict(spec)
                if max_rows is not None and max_rows > 0:
                    cur_limit = active_spec.get("limit")
                    if cur_limit is None or int(cur_limit) > max_rows:
                        active_spec["limit"] = max_rows

                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(
                        active_spec,
                        schema=body.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )

                res = _exec_conn_method(
                    conn,
                    "execute",
                    active_spec,
                    statement_timeout_ms=eff_timeout,
                )
                out = res.to_dict() if hasattr(res, "to_dict") else dict(res)
                if (
                    max_rows is not None
                    and max_rows > 0
                    and isinstance(out.get("rows"), list)
                ):
                    out["rows"] = out["rows"][:max_rows]
                    out["count"] = len(out["rows"])
                return _json_resp(out)

            if not allow_raw_sql or not effective_capabilities.is_enabled("raw_sql"):
                return _json_resp(
                    {"error": "Feature 'raw_sql' is disabled in engine capabilities."},
                    status_code=403,
                )
            if _is_tenant_active(tenant_ctx):
                return _json_resp(
                    {"error": "Raw SQL execution restricted under tenant isolation."},
                    status_code=403,
                )

            val_res = validate_sql_ast(
                str(sql), allowed_schemas=body.get("allowed_schemas")
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                return _json_resp(
                    {"error": f"Security violation: {'; '.join(violations)}"},
                    status_code=403,
                )

            cols, rows, latency = _exec_conn_method(
                conn,
                "execute_raw",
                str(sql),
                body.get("params") or [],
                statement_timeout_ms=eff_timeout,
            )
            if max_rows is not None and max_rows > 0:
                rows = rows[:max_rows]
            return _json_resp(
                {
                    "columns": cols,
                    "rows": rows,
                    "count": len(rows),
                    "latency_ms": round(latency, 2),
                    "dialect": getattr(conn, "dialect_name", "sqlite"),
                    "sql": sql,
                }
            )
        except PermissionError as exc:
            return _json_resp({"error": _unauthorized_message(exc)}, status_code=401)
        except DisabledFeatureError as exc:
            return _json_resp(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status_code=403,
            )
        except SecurityError as exc:
            return _json_resp({"error": str(exc)}, status_code=403)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Execution failed", exc)}, status_code=400
            )

    def _resolve_export_payload(body: dict[str, Any], request: Any) -> dict[str, Any]:
        conn = _resolve_conn(connector)
        tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
        if body.get("rows") is not None:
            rows_in = body["rows"]
            if max_rows is not None and max_rows > 0 and isinstance(rows_in, list):
                rows_in = rows_in[:max_rows]
            return {"rows": rows_in, "columns": body.get("columns", [])}
        if body.get("spec") is not None:
            spec_in = body["spec"]
            if isinstance(spec_in, dict):
                if spec_in.get("ctes"):
                    effective_capabilities.require_feature("ctes")
                if spec_in.get("window_functions"):
                    effective_capabilities.require_feature("window_functions")
                if (
                    spec_in.get("rollup")
                    or spec_in.get("cube")
                    or spec_in.get("grouping_sets")
                    or spec_in.get("pivot")
                ):
                    effective_capabilities.require_feature("analytical_grouping")
                if spec_in.get("vector_search") or spec_in.get("hybrid_search"):
                    effective_capabilities.require_feature("vector_search")
            active_spec = dict(spec_in) if isinstance(spec_in, dict) else spec_in
            if max_rows is not None and max_rows > 0 and isinstance(active_spec, dict):
                cur_limit = active_spec.get("limit")
                if cur_limit is None or int(cur_limit) > max_rows:
                    active_spec["limit"] = max_rows
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    active_spec,
                    schema=body.get("schema"),
                    context=tenant_ctx,
                    policy=policy,
                )
            res = _exec_conn_method(conn, "execute", active_spec)
            rows_out = (
                res.get("rows", [])
                if isinstance(res, dict)
                else getattr(res, "rows", [])
            )
            if max_rows is not None and max_rows > 0 and isinstance(rows_out, list):
                rows_out = rows_out[:max_rows]
            return {
                "rows": rows_out,
                "columns": res.get("columns", [])
                if isinstance(res, dict)
                else getattr(res, "columns", []),
            }
        if body.get("sql") is not None:
            if not allow_raw_sql or not effective_capabilities.is_enabled("raw_sql"):
                raise SecurityError(
                    "Feature 'raw_sql' is disabled in engine capabilities."
                )
            if _is_tenant_active(tenant_ctx):
                raise SecurityError("Raw SQL export restricted under tenant isolation.")
            val_res = validate_sql_ast(
                str(body["sql"]), allowed_schemas=body.get("allowed_schemas")
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise SecurityError(f"Security violation: {'; '.join(violations)}")
            cols, rows, _ = _exec_conn_method(
                conn, "execute_raw", str(body["sql"]), body.get("params") or []
            )
            if max_rows is not None and max_rows > 0 and isinstance(rows, list):
                rows = rows[:max_rows]
            return {"rows": rows, "columns": cols}
        raise ExportError("Missing export data source")

    @post(path=["/export", "/v1/export"])
    async def export_query(data: dict[str, Any], request: Any = None) -> Any:
        try:
            body = data if isinstance(data, dict) else {}
            fmt = body.get("format", "csv")
            export_data = _resolve_export_payload(body, request)
            if body.get("stream", False):
                stream_iter, mime_type, ext = stream_export_dataset(
                    export_data, format=fmt
                )
                return Stream(
                    stream_iter,
                    media_type=mime_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="export.{ext}"'
                    },
                )
            content_bytes, mime_type, ext = export_dataset(export_data, format=fmt)
            return Response(
                content=content_bytes,
                status_code=200,
                media_type=mime_type,
                headers={"Content-Disposition": f'attachment; filename="export.{ext}"'},
            )
        except PermissionError as exc:
            return _json_resp({"error": _unauthorized_message(exc)}, status_code=401)
        except DisabledFeatureError as exc:
            return _json_resp(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status_code=403,
            )
        except SecurityError as exc:
            return _json_resp({"error": str(exc)}, status_code=403)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Export failed", exc)}, status_code=400
            )

    @post(path=["/export/stream", "/v1/export/stream"])
    async def export_stream_query(data: dict[str, Any], request: Any = None) -> Any:
        try:
            body = data if isinstance(data, dict) else {}
            fmt = body.get("format", "csv")
            export_data = _resolve_export_payload(body, request)
            stream_iter, mime_type, ext = stream_export_dataset(export_data, format=fmt)
            return Stream(
                stream_iter,
                media_type=mime_type,
                headers={"Content-Disposition": f'attachment; filename="export.{ext}"'},
            )
        except PermissionError as exc:
            return _json_resp({"error": _unauthorized_message(exc)}, status_code=401)
        except DisabledFeatureError as exc:
            return _json_resp(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status_code=403,
            )
        except SecurityError as exc:
            return _json_resp({"error": str(exc)}, status_code=403)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Streaming export failed", exc)},
                status_code=400,
            )

    @post(path=["/explain", "/v1/explain"])
    async def explain_query(data: dict[str, Any], request: Any = None) -> Any:
        conn = _resolve_conn(connector)
        try:
            body = data if isinstance(data, dict) else {}
            target_spec = body.get("spec") or body.get("query")
            if (
                not target_spec
                or not isinstance(target_spec, dict)
                or not target_spec.get("table")
            ):
                return _json_resp(
                    {"error": "Missing required 'table' in query specification."},
                    status_code=400,
                )
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            schema_snap = body.get("schema") or body.get("schema_snapshot")
            active_spec = target_spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    target_spec,
                    schema=schema_snap,
                    context=tenant_ctx,
                    policy=policy,
                )
            dialect = body.get("dialect") or getattr(conn, "dialect_name", "postgres")
            compiler = QueryCompiler(
                active_spec,
                schema=schema_snap,
                dialect=dialect,
                capabilities=effective_capabilities,
            )
            sql, params = compiler.compile()[0:2]
            plan = estimate_plan_from_spec(active_spec, schema=schema_snap)
            perf = analyze_query_performance(
                active_spec,
                sql=sql,
                dialect=str(dialect or "postgres"),
                schema_snapshot=schema_snap,
            )
            rec_indexes = recommend_indexes(active_spec, schema_snapshot=schema_snap)
            return _json_resp(
                {
                    "sql": sql,
                    "params": params,
                    "dialect": dialect,
                    "plan": plan.to_dict() if hasattr(plan, "to_dict") else plan,
                    "performance": perf,
                    "recommended_indexes": rec_indexes,
                }
            )
        except PermissionError as exc:
            return _json_resp({"error": _unauthorized_message(exc)}, status_code=401)
        except DisabledFeatureError as exc:
            return _json_resp(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status_code=403,
            )
        except SecurityError as exc:
            return _json_resp({"error": str(exc)}, status_code=403)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Explain failed", exc)}, status_code=400
            )

    @post(path=["/join-path", "/v1/join-path"])
    async def join_path_query(data: dict[str, Any]) -> Any:
        try:
            body = data if isinstance(data, dict) else {}
            active_tables = body.get("active_tables", [])
            target_table = body.get("target_table", "")
            if not active_tables or not target_table:
                return _json_resp(
                    {"error": "Both 'active_tables' and 'target_table' are required."},
                    status_code=400,
                )
            schema_data = body.get("schema") or body.get("schema_snapshot")
            if schema_data is None:
                conn = _resolve_conn(connector)
                raw_schema = _exec_conn_method(conn, "introspect_schema")
                schema_data = _normalize_schema_snapshot(raw_schema)
            schema_data = _filter_schema_tables(schema_data, policy)
            path_steps = find_join_path(
                active_tables,
                target_table,
                schema_data=schema_data,
            )
            return _json_resp(
                {
                    "path": path_steps,
                    "connected": bool(path_steps),
                    "target_table": target_table,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("Join path solver failed", exc)},
                status_code=400,
            )

    @post(path=["/nlq", "/v1/nlq", "/nlq/translate", "/v1/nlq/translate"])
    async def nlq_query(data: dict[str, Any], request: Any = None) -> Any:
        try:
            body = data if isinstance(data, dict) else {}
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                return _json_resp(
                    {"error": "Prompt must not be empty."}, status_code=400
                )
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            schema_data = body.get("schema") or body.get("schema_snapshot")
            if schema_data is None:
                raw_schema = _exec_conn_method(conn, "introspect_schema")
                schema_data = _normalize_schema_snapshot(raw_schema)
            schema_data = _filter_schema_tables(schema_data, policy)
            dialect_str = str(
                body.get("dialect")
                or getattr(conn, "dialect_name", "postgres")
                or "postgres"
            )
            if nlq_service is not None:
                nlq_res = nlq_service.translate(
                    {
                        "prompt": prompt,
                        "schema": schema_data,
                        "dialect": dialect_str,
                        "provider": body.get("provider"),
                        "api_key": body.get("api_key"),
                        "model": body.get("model"),
                        "current_spec": body.get("current_spec"),
                        "history": body.get("history"),
                    }
                )
                raw_spec = dict(nlq_res.spec)
                explanation = nlq_res.explanation
                confidence = nlq_res.confidence
                warnings = list(nlq_res.warnings)
            else:
                from query_builder.ai.client import ask_ai

                ai_res = ask_ai(
                    prompt=prompt,
                    ai=ai_provider,
                    schema=schema_data,
                    dialect=dialect_str,
                    options=body.get("options"),
                )
                raw_spec = dict(ai_res.spec)
                explanation = ai_res.explanation
                confidence = ai_res.confidence
                warnings = list(ai_res.warnings)

            if policy is not None or tenant_ctx is not None:
                raw_spec = apply_security_policy(
                    raw_spec,
                    schema=schema_data,
                    context=tenant_ctx,
                    policy=policy,
                )
            compiler = QueryCompiler(
                raw_spec,
                schema=schema_data,
                dialect=dialect_str,
                capabilities=effective_capabilities,
            )
            final_sql, final_params = compiler.compile()[0:2]
            return _json_resp(
                {
                    "spec": raw_spec,
                    "sql": final_sql,
                    "params": final_params,
                    "explanation": explanation,
                    "confidence": confidence,
                    "warnings": warnings,
                }
            )
        except PermissionError as exc:
            return _json_resp({"error": _unauthorized_message(exc)}, status_code=401)
        except DisabledFeatureError as exc:
            return _json_resp(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status_code=403,
            )
        except SecurityError as exc:
            return _json_resp({"error": str(exc)}, status_code=403)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("NLQ translation failed", exc)},
                status_code=400,
            )

    @post(path=["/nlq/explain", "/v1/nlq/explain"])
    async def nlq_explain_query(data: dict[str, Any]) -> Any:
        try:
            body = data if isinstance(data, dict) else {}
            target_spec = body.get("spec") or body.get("query")
            if not target_spec or not isinstance(target_spec, dict):
                return _json_resp(
                    {"error": "Missing required 'spec' or 'query' for explanation."},
                    status_code=400,
                )
            conn = _resolve_conn(connector)
            dialect_str = str(
                body.get("dialect")
                or getattr(conn, "dialect_name", "postgres")
                or "postgres"
            )
            if nlq_service is not None:
                exp = nlq_service.explain(
                    target_spec,
                    dialect=dialect_str,
                    provider=body.get("provider") or nlq_service.default_provider,
                    api_key=body.get("api_key"),
                    model=body.get("model"),
                )
            else:
                from query_builder.nlq import NlqService

                exp = NlqService().explain(
                    target_spec,
                    dialect=dialect_str,
                    provider=body.get("provider") or "mock",
                    api_key=body.get("api_key"),
                    model=body.get("model"),
                )
            payload_out = exp.to_dict() if hasattr(exp, "to_dict") else dict(exp)
            return _json_resp(payload_out)
        except Exception as exc:  # noqa: BLE001
            return _json_resp(
                {"error": public_error("NLQ explain failed", exc)},
                status_code=400,
            )

    @get(path=["/nlq/providers", "/v1/nlq/providers"])
    async def nlq_providers_query() -> Any:
        from query_builder.nlq import NlqService, list_nlq_providers

        default_prov = (
            getattr(nlq_service, "default_provider", "mock")
            if nlq_service is not None
            else NlqService().default_provider
        )
        return _json_resp(
            {
                "providers": list_nlq_providers(),
                "default": default_prov,
                "default_provider": default_prov,
            }
        )

    route_handlers = [
        get_capabilities,
        get_schema,
        compile_query,
        validate_query,
        execute_query,
        export_query,
        export_stream_query,
        explain_query,
        join_path_query,
        nlq_query,
        nlq_explain_query,
        nlq_providers_query,
    ]

    return Router(
        path=path or "/",
        route_handlers=route_handlers,
        tags=tags or ["Query Builder"],
    )


__all__ = ["create_litestar_router"]
