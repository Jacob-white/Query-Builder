"""
Flask Blueprint Integration for Query-Builder.
==============================================
Turnkey production-ready Flask Blueprint factory registering:
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
import json
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


def _get_flask() -> tuple[Any, Any, Any]:
    """Lazily imports Flask components `(Blueprint, Response, request)`."""
    try:
        flask_mod = importlib.import_module("flask")
        if flask_mod is None:
            raise ImportError("Flask is not installed")
        return flask_mod.Blueprint, flask_mod.Response, flask_mod.request
    except ImportError as exc:
        raise ImportError(
            "Flask is not installed. Install via 'pip install flask' to use create_flask_blueprint."
        ) from exc


def _json_response(response_cls: Any, payload: Any, status: int = 200) -> Any:
    """Constructs a JSON Flask Response with standard content-type."""
    return response_cls(
        json.dumps(payload, default=str),
        status=status,
        mimetype="application/json",
    )


def create_flask_blueprint(
    connector: Any,
    *,
    security: SecurityPolicy | dict[str, Any] | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    tenant_resolver: Callable[[Any], TenantContext | dict[str, Any] | str | None]
    | None = None,
    url_prefix: str = "",
    name: str = "query_builder",
    schema_cache_ttl: float = 300.0,
    max_rows: int | None = None,
    statement_timeout_ms: int | None = None,
    allow_raw_sql: bool = True,
    ai_provider: Any = None,
    nlq_service: Any = None,
) -> Any:
    """Creates and returns a configured Flask Blueprint for Query-Builder."""
    Blueprint, Response, flask_request = _get_flask()
    prefix = url_prefix.rstrip("/") if url_prefix else ""
    bp = Blueprint(name, __name__, url_prefix=prefix or None)

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

    def _get_body() -> dict[str, Any]:
        if hasattr(flask_request, "get_json"):
            data = flask_request.get_json(silent=True)
            if isinstance(data, dict):
                return data
        raw = getattr(flask_request, "data", b"")
        if raw:
            try:
                parsed = json.loads(
                    raw.decode("utf-8") if isinstance(raw, bytes) else raw
                )
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, UnicodeDecodeError):
                return {}
        return {}

    def _is_tenant_active(tenant_ctx: TenantContext | None) -> bool:
        return bool(
            tenant_ctx is not None
            or tenant_resolver is not None
            or (policy is not None and policy.enforce_tenant_isolation)
        )

    def handle_capabilities() -> Any:
        return _json_response(
            Response, {"capabilities": effective_capabilities.to_dict()}
        )

    def handle_schema() -> Any:
        nonlocal cached_schema_data, cached_schema_time
        args = getattr(flask_request, "args", {}) or {}
        refresh = str(args.get("refresh", "")).lower() in ("true", "1")
        if (
            not refresh
            and schema_cache_ttl > 0.0
            and cached_schema_data is not None
            and (time.monotonic() - cached_schema_time) < schema_cache_ttl
        ):
            return _json_response(Response, cached_schema_data)

        conn = _resolve_conn(connector)
        try:
            snapshot = _exec_conn_method(conn, "introspect_schema")
            data = _normalize_schema_snapshot(snapshot)
            data["capabilities"] = effective_capabilities.to_dict()
            data = _filter_schema_tables(data, policy)
            if schema_cache_ttl > 0.0:
                cached_schema_data = dict(data)
                cached_schema_time = time.monotonic()
            return _json_response(Response, data)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Schema introspection failed", exc)},
                status=500,
            )

    def handle_compile() -> Any:
        conn = _resolve_conn(connector)
        try:
            body = _get_body()
            tenant_ctx = _resolve_tenant_sync(flask_request, tenant_resolver)
            spec = body.get("spec")
            if not spec or not isinstance(spec, dict):
                return _json_response(
                    Response, {"error": "Missing required 'spec'"}, status=400
                )

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
                return _json_response(
                    Response,
                    {"error": f"Security violation: {'; '.join(violations)}"},
                    status=403,
                )
            return _json_response(
                Response,
                {
                    "sql": main_sql,
                    "params": params,
                    "count_sql": count_sql,
                    "count_params": count_params,
                    "dialect": dialect,
                },
            )
        except PermissionError as exc:
            return _json_response(
                Response, {"error": _unauthorized_message(exc)}, status=401
            )
        except DisabledFeatureError as exc:
            return _json_response(
                Response,
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return _json_response(Response, {"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Compilation failed", exc)},
                status=400,
            )

    def handle_validate() -> Any:
        try:
            body = _get_body()
            sql = body.get("sql")
            if not sql or not isinstance(sql, str):
                return _json_response(
                    Response, {"error": "Missing required 'sql'"}, status=400
                )
            res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
            return _json_response(Response, res)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Validation failed", exc)},
                status=400,
            )

    def handle_execute() -> Any:
        conn = _resolve_conn(connector)
        try:
            body = _get_body()
            tenant_ctx = _resolve_tenant_sync(flask_request, tenant_resolver)
            spec = body.get("spec") or body.get("query")
            sql = body.get("sql")
            if not spec and not sql:
                return _json_response(
                    Response,
                    {"error": "Either 'spec' or 'sql' must be provided"},
                    status=400,
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
                return _json_response(Response, out)

            if not allow_raw_sql or not effective_capabilities.is_enabled("raw_sql"):
                return _json_response(
                    Response,
                    {"error": "Feature 'raw_sql' is disabled in engine capabilities."},
                    status=403,
                )
            if _is_tenant_active(tenant_ctx):
                return _json_response(
                    Response,
                    {"error": "Raw SQL execution restricted under tenant isolation."},
                    status=403,
                )

            val_res = validate_sql_ast(
                str(sql), allowed_schemas=body.get("allowed_schemas")
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                return _json_response(
                    Response,
                    {"error": f"Security violation: {'; '.join(violations)}"},
                    status=403,
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
            return _json_response(
                Response,
                {
                    "columns": cols,
                    "rows": rows,
                    "count": len(rows),
                    "latency_ms": round(latency, 2),
                    "dialect": getattr(conn, "dialect_name", "sqlite"),
                    "sql": sql,
                },
            )
        except PermissionError as exc:
            return _json_response(
                Response, {"error": _unauthorized_message(exc)}, status=401
            )
        except DisabledFeatureError as exc:
            return _json_response(
                Response,
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return _json_response(Response, {"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Execution failed", exc)},
                status=400,
            )

    def _resolve_export_payload(body: dict[str, Any]) -> dict[str, Any]:
        conn = _resolve_conn(connector)
        tenant_ctx = _resolve_tenant_sync(flask_request, tenant_resolver)
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

    def handle_export() -> Any:
        try:
            body = _get_body()
            fmt = body.get("format", "csv")
            export_data = _resolve_export_payload(body)
            if body.get("stream", False):
                stream_iter, mime_type, ext = stream_export_dataset(
                    export_data, format=fmt
                )
                return Response(
                    stream_iter,
                    status=200,
                    mimetype=mime_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="export.{ext}"'
                    },
                )
            content_bytes, mime_type, ext = export_dataset(export_data, format=fmt)
            return Response(
                content_bytes,
                status=200,
                mimetype=mime_type,
                headers={"Content-Disposition": f'attachment; filename="export.{ext}"'},
            )
        except PermissionError as exc:
            return _json_response(
                Response, {"error": _unauthorized_message(exc)}, status=401
            )
        except DisabledFeatureError as exc:
            return _json_response(
                Response,
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return _json_response(Response, {"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Export failed", exc)},
                status=400,
            )

    def handle_export_stream() -> Any:
        try:
            body = _get_body()
            fmt = body.get("format", "csv")
            export_data = _resolve_export_payload(body)
            stream_iter, mime_type, ext = stream_export_dataset(export_data, format=fmt)
            return Response(
                stream_iter,
                status=200,
                mimetype=mime_type,
                headers={"Content-Disposition": f'attachment; filename="export.{ext}"'},
            )
        except PermissionError as exc:
            return _json_response(
                Response, {"error": _unauthorized_message(exc)}, status=401
            )
        except DisabledFeatureError as exc:
            return _json_response(
                Response,
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return _json_response(Response, {"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Streaming export failed", exc)},
                status=400,
            )

    def handle_explain() -> Any:
        conn = _resolve_conn(connector)
        try:
            body = _get_body()
            target_spec = body.get("spec") or body.get("query")
            if (
                not target_spec
                or not isinstance(target_spec, dict)
                or not target_spec.get("table")
            ):
                return _json_response(
                    Response,
                    {"error": "Missing required 'table' in query specification."},
                    status=400,
                )
            tenant_ctx = _resolve_tenant_sync(flask_request, tenant_resolver)
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
            return _json_response(
                Response,
                {
                    "sql": sql,
                    "params": params,
                    "dialect": dialect,
                    "plan": plan.to_dict() if hasattr(plan, "to_dict") else plan,
                    "performance": perf,
                    "recommended_indexes": rec_indexes,
                },
            )
        except PermissionError as exc:
            return _json_response(
                Response, {"error": _unauthorized_message(exc)}, status=401
            )
        except DisabledFeatureError as exc:
            return _json_response(
                Response,
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return _json_response(Response, {"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Explain failed", exc)},
                status=400,
            )

    def handle_join_path() -> Any:
        try:
            body = _get_body()
            active_tables = body.get("active_tables", [])
            target_table = body.get("target_table", "")
            if not active_tables or not target_table:
                return _json_response(
                    Response,
                    {"error": "Both 'active_tables' and 'target_table' are required."},
                    status=400,
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
            return _json_response(
                Response,
                {
                    "path": path_steps,
                    "connected": bool(path_steps),
                    "target_table": target_table,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("Join path solver failed", exc)},
                status=400,
            )

    def handle_nlq() -> Any:
        try:
            body = _get_body()
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                return _json_response(
                    Response, {"error": "Prompt must not be empty."}, status=400
                )
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(flask_request, tenant_resolver)
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
            return _json_response(
                Response,
                {
                    "spec": raw_spec,
                    "sql": final_sql,
                    "params": final_params,
                    "explanation": explanation,
                    "confidence": confidence,
                    "warnings": warnings,
                },
            )
        except PermissionError as exc:
            return _json_response(
                Response, {"error": _unauthorized_message(exc)}, status=401
            )
        except DisabledFeatureError as exc:
            return _json_response(
                Response,
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return _json_response(Response, {"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("NLQ translation failed", exc)},
                status=400,
            )

    def handle_nlq_explain() -> Any:
        try:
            body = _get_body()
            target_spec = body.get("spec") or body.get("query")
            if not target_spec or not isinstance(target_spec, dict):
                return _json_response(
                    Response,
                    {"error": "Missing required 'spec' or 'query' for explanation."},
                    status=400,
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
            return _json_response(Response, payload_out)
        except Exception as exc:  # noqa: BLE001
            return _json_response(
                Response,
                {"error": public_error("NLQ explain failed", exc)},
                status=400,
            )

    def handle_nlq_providers() -> Any:
        from query_builder.nlq import NlqService, list_nlq_providers

        default_prov = (
            getattr(nlq_service, "default_provider", "mock")
            if nlq_service is not None
            else NlqService().default_provider
        )
        return _json_response(
            Response,
            {
                "providers": list_nlq_providers(),
                "default": default_prov,
                "default_provider": default_prov,
            },
        )

    routes: list[tuple[str, str, Callable[[], Any], list[str]]] = [
        ("/capabilities", "capabilities", handle_capabilities, ["GET"]),
        ("/v1/capabilities", "v1_capabilities", handle_capabilities, ["GET"]),
        ("/schema", "schema", handle_schema, ["GET"]),
        ("/v1/schema", "v1_schema", handle_schema, ["GET"]),
        ("/introspect", "introspect", handle_schema, ["GET"]),
        ("/compile", "compile", handle_compile, ["POST"]),
        ("/v1/compile", "v1_compile", handle_compile, ["POST"]),
        ("/validate", "validate", handle_validate, ["POST"]),
        ("/v1/validate", "v1_validate", handle_validate, ["POST"]),
        ("/execute", "execute", handle_execute, ["POST"]),
        ("/v1/execute", "v1_execute", handle_execute, ["POST"]),
        ("/export", "export", handle_export, ["POST"]),
        ("/v1/export", "v1_export", handle_export, ["POST"]),
        ("/export/stream", "export_stream", handle_export_stream, ["POST"]),
        ("/v1/export/stream", "v1_export_stream", handle_export_stream, ["POST"]),
        ("/explain", "explain", handle_explain, ["POST"]),
        ("/v1/explain", "v1_explain", handle_explain, ["POST"]),
        ("/join-path", "join_path", handle_join_path, ["POST"]),
        ("/v1/join-path", "v1_join_path", handle_join_path, ["POST"]),
        ("/nlq", "nlq", handle_nlq, ["POST"]),
        ("/v1/nlq", "v1_nlq", handle_nlq, ["POST"]),
        ("/nlq/translate", "nlq_translate", handle_nlq, ["POST"]),
        ("/v1/nlq/translate", "v1_nlq_translate", handle_nlq, ["POST"]),
        ("/nlq/explain", "nlq_explain", handle_nlq_explain, ["POST"]),
        ("/v1/nlq/explain", "v1_nlq_explain", handle_nlq_explain, ["POST"]),
        ("/nlq/providers", "nlq_providers", handle_nlq_providers, ["GET"]),
        ("/v1/nlq/providers", "v1_nlq_providers", handle_nlq_providers, ["GET"]),
    ]

    for rule, endpoint_name, view_fn, methods in routes:
        bp.add_url_rule(
            rule, endpoint=endpoint_name, view_func=view_fn, methods=methods
        )

    return bp


__all__ = ["create_flask_blueprint"]
