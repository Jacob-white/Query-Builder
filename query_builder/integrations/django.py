"""
Django, Django REST Framework, and Django Ninja Integrations for Query-Builder.
================================================================================
Turnkey integrations for Django web applications:
- `create_django_urls` : Standard Django URL patterns and views (`django.urls.path`)
- `create_drf_views`   : Django REST Framework `APIView` class suite
- `create_ninja_router`: Django Ninja `Router` with typed schema validation

Optional/Lazy Dependency Support:
---------------------------------
All imports of django, rest_framework, and ninja are guarded. If an optional
dependency is not installed in the current environment, an informative
ImportError is raised only when invoking the specific factory function.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.config import SecurityConfig
from query_builder.connectors.registry import get_connector
from query_builder.export import ExportError, export_dataset
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.security import SecurityError

# Guarded imports
try:
    import django
    from django.http import HttpRequest, HttpResponse, JsonResponse
    from django.urls import path
    from django.views.decorators.csrf import csrf_exempt

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    HttpRequest = Any  # type: ignore[misc, assignment]
    HttpResponse = Any  # type: ignore[misc, assignment]
    JsonResponse = Any  # type: ignore[misc, assignment]

try:
    import rest_framework
    from rest_framework.exceptions import PermissionDenied, ValidationError
    from rest_framework.request import Request as DRFRequest
    from rest_framework.response import Response as DRFResponse
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    APIView = object  # type: ignore[misc, assignment]
    DRFRequest = Any  # type: ignore[misc, assignment]
    DRFResponse = Any  # type: ignore[misc, assignment]

try:
    import ninja
    from ninja import Router as NinjaRouter
    from ninja.errors import HttpError

    NINJA_AVAILABLE = True
except ImportError:
    NINJA_AVAILABLE = False
    NinjaRouter = Any  # type: ignore[misc, assignment]


def _resolve_conn(connector: Any) -> Any:
    """Resolves connector from instance, factory callable, or name string."""
    if isinstance(connector, str):
        return get_connector(connector)
    if callable(connector) and not hasattr(connector, "execute"):
        res = connector()
        if inspect.isawaitable(res):
            import asyncio
            import concurrent.futures
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, res).result()
            else:
                return asyncio.run(res)
        return res
    return connector


def _exec_conn_method(conn: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Executes a connector method supporting both synchronous and asynchronous connectors safely."""
    method = getattr(conn, method_name)
    call_kwargs = dict(kwargs)
    if "statement_timeout_ms" in call_kwargs and call_kwargs["statement_timeout_ms"] is None:
        call_kwargs.pop("statement_timeout_ms")
    elif "statement_timeout_ms" in call_kwargs:
        try:
            sig = inspect.signature(method)
            has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not has_var_kwargs and "statement_timeout_ms" not in sig.parameters:
                call_kwargs.pop("statement_timeout_ms")
        except (ValueError, TypeError):
            pass

    if inspect.iscoroutinefunction(method):
        import asyncio
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, method(*args, **call_kwargs)).result()
        else:
            return asyncio.run(method(*args, **call_kwargs))

    res = method(*args, **call_kwargs)
    if inspect.isawaitable(res):
        import asyncio
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, res).result()
        else:
            return asyncio.run(res)
    return res


def _filter_schema_tables(data: dict[str, Any], policy: SecurityPolicy | None) -> dict[str, Any]:
    """Filters schema snapshot tables according to policy allow/restricted lists."""
    if policy and "tables" in data and isinstance(data["tables"], dict):
        allowed = set(policy.allowed_tables) if policy.allowed_tables is not None else None
        restricted = set(policy.restricted_tables or [])
        data["tables"] = {
            tname: tmeta
            for tname, tmeta in data["tables"].items()
            if (allowed is None or tname in allowed) and tname not in restricted
        }
    return data


def _normalize_schema_snapshot(snapshot: Any) -> dict[str, Any]:
    """Converts a schema snapshot (dataclass, dict, or to_dict object) into a standard dictionary."""
    if is_dataclass(snapshot) and not isinstance(snapshot, type):
        return asdict(snapshot)
    if hasattr(snapshot, "to_dict"):
        return snapshot.to_dict()
    if isinstance(snapshot, dict):
        return dict(snapshot)
    try:
        return dict(snapshot)
    except Exception:
        return {"tables": {}}


def _resolve_tenant_sync(
    request: Any,
    tenant_resolver: Callable[[Any], TenantContext | dict[str, Any] | str | None] | None,
) -> TenantContext | None:
    """Resolves tenant context synchronously, failing closed if configured."""
    if tenant_resolver is None:
        return None

    res = tenant_resolver(request)
    if inspect.isawaitable(res):
        import asyncio
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                res = pool.submit(asyncio.run, res).result()
        else:
            res = asyncio.run(res)

    if res is None:
        raise PermissionError("Unauthorized: TenantContext could not be resolved from request.")

    if isinstance(res, TenantContext):
        ctx = res
    elif isinstance(res, str):
        ctx = TenantContext(tenant_id=res)
    elif isinstance(res, dict):
        known_fields = {"tenant_id", "user_id", "roles", "attributes"}
        d = dict(res)
        extra = {k: v for k, v in d.items() if k not in known_fields}
        attrs = dict(d.get("attributes") or {})
        attrs.update(extra)
        ctx = TenantContext(
            tenant_id=str(d.get("tenant_id", "")),
            user_id=d.get("user_id"),
            roles=d.get("roles") or [],
            attributes=attrs,
        )
    else:
        raise PermissionError(f"Unauthorized: Invalid tenant context type '{type(res).__name__}'.")

    if not ctx.tenant_id or not str(ctx.tenant_id).strip():
        raise PermissionError("Unauthorized: Resolved TenantContext contains empty tenant_id.")

    return ctx


def _get_effective_policy(
    security: SecurityPolicy | SecurityConfig | dict[str, Any] | None,
    has_tenant_resolver: bool,
) -> SecurityPolicy | None:
    """Determines the active SecurityPolicy."""
    if security is None:
        if has_tenant_resolver:
            return SecurityPolicy(enforce_tenant_isolation=True)
        return None
    if isinstance(security, SecurityPolicy):
        if has_tenant_resolver:
            security.enforce_tenant_isolation = True
        return security
    if isinstance(security, dict):
        pol = SecurityPolicy(**security)
        if has_tenant_resolver:
            pol.enforce_tenant_isolation = True
        return pol
    if hasattr(security, "privacy"):
        # SecurityConfig instance
        pol = SecurityPolicy(
            allowed_tables=getattr(getattr(security, "privacy", None), "allowed_tables", None),
            restricted_tables=getattr(getattr(security, "privacy", None), "restricted_tables", []),
            tenant_column=getattr(security.privacy, "tenant_column", "tenant_id"),
            enforce_tenant_isolation=True if has_tenant_resolver else getattr(security.privacy, "enforce_tenant_isolation", False),
            sensitive_column_patterns=getattr(security.privacy, "sensitive_column_patterns", []),
            masking_strategy=getattr(security.privacy, "masking_strategy", "redact"),
            max_complexity_score=getattr(security.execution, "max_complexity_score", None) if hasattr(security, "execution") else None,
        )
        return pol
    return security


def create_django_urls(
    connector: Any,
    security: SecurityPolicy | dict[str, Any] | None = None,
    tenant_resolver: Callable[[HttpRequest], TenantContext | dict[str, Any] | str | None] | None = None,
) -> list[Any]:
    """Generates standard Django URL patterns for Query-Builder.

    Parameters
    ----------
    connector:
        Database connector instance, factory callable, or connector name string.
    security:
        Security policy configuration.
    tenant_resolver:
        Callable taking Django HttpRequest and returning TenantContext.

    Returns
    -------
    list of django.urls.path
    """
    if not DJANGO_AVAILABLE:
        raise ImportError(
            "Django is not installed. Install it via 'pip install django' to use create_django_urls."
        )

    policy = _get_effective_policy(security, tenant_resolver is not None)

    @csrf_exempt
    def schema_view(request: HttpRequest) -> HttpResponse:
        if request.method != "GET":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        conn = _resolve_conn(connector)
        try:
            snapshot = _exec_conn_method(conn, "introspect_schema")
            data = _normalize_schema_snapshot(snapshot)
            data = _filter_schema_tables(data, policy)
            return JsonResponse(data, safe=False)
        except Exception as exc:
            return JsonResponse({"error": f"Schema introspection failed: {exc}"}, status=500)

    @csrf_exempt
    def compile_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        conn = _resolve_conn(connector)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = body.get("spec")
            if not spec:
                return JsonResponse({"error": "Missing required 'spec'"}, status=400)

            active_spec = spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    spec,
                    schema=body.get("schema"),
                    context=tenant_ctx,
                    policy=policy,
                )

            dialect = body.get("dialect") or getattr(conn, "dialect_name", "postgres")
            compiler = QueryCompiler(active_spec, schema=body.get("schema"), dialect=dialect)
            main_sql, params, count_sql, count_params = compiler.compile()
            return JsonResponse({
                "sql": main_sql,
                "params": params,
                "count_sql": count_sql,
                "count_params": count_params,
                "dialect": dialect,
            })
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=401)
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:
            return JsonResponse({"error": f"Compilation failed: {exc}"}, status=400)

    @csrf_exempt
    def validate_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            sql = body.get("sql")
            if not sql:
                return JsonResponse({"error": "Missing required 'sql'"}, status=400)
            res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
            return JsonResponse(res, safe=False)
        except Exception as exc:
            return JsonResponse({"error": f"Validation failed: {exc}"}, status=400)

    @csrf_exempt
    def execute_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        conn = _resolve_conn(connector)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)

            spec = body.get("spec") or body.get("query")
            sql = body.get("sql")
            if not spec and not sql:
                return JsonResponse({"error": "Either 'spec' or 'sql' must be provided"}, status=400)

            if spec is not None:
                active_spec = spec
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(spec, context=tenant_ctx, policy=policy)
                result = _exec_conn_method(conn, "execute", active_spec, statement_timeout_ms=body.get("timeout_ms"))
                if hasattr(result, "to_dict"):
                    return JsonResponse(result.to_dict(), safe=False)
                if isinstance(result, dict):
                    return JsonResponse(result, safe=False)
                return JsonResponse({
                    "columns": getattr(result, "columns", []),
                    "rows": getattr(result, "rows", []),
                    "count": len(getattr(result, "rows", [])),
                    "latency_ms": getattr(result, "latency_ms", 0.0),
                    "dialect": getattr(conn, "dialect_name", "sqlite"),
                    "sql": getattr(result, "sql", ""),
                })

            if policy and getattr(policy, "enforce_tenant_isolation", False):
                return JsonResponse(
                    {"error": "Raw SQL execution restricted under tenant isolation."}, status=403
                )

            cols, rows, latency = _exec_conn_method(conn, "execute_raw", sql, body.get("params") or [])
            return JsonResponse({
                "columns": cols,
                "rows": rows,
                "count": len(rows),
                "latency_ms": round(latency, 2),
                "dialect": getattr(conn, "dialect_name", "sqlite"),
                "sql": sql,
            })
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=401)
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:
            return JsonResponse({"error": f"Execution failed: {exc}"}, status=400)

    @csrf_exempt
    def export_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        conn = _resolve_conn(connector)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            fmt = body.get("format", "csv")

            if body.get("rows") is not None:
                export_data = {"rows": body["rows"], "columns": body.get("columns", [])}
            elif body.get("spec") is not None:
                active_spec = body["spec"]
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(active_spec, context=tenant_ctx, policy=policy)
                res = _exec_conn_method(conn, "execute", active_spec)
                export_data = {
                    "rows": res.get("rows", []) if isinstance(res, dict) else getattr(res, "rows", []),
                    "columns": res.get("columns", []) if isinstance(res, dict) else getattr(res, "columns", []),
                }
            elif body.get("sql") is not None:
                if policy and getattr(policy, "enforce_tenant_isolation", False):
                    return JsonResponse(
                        {"error": "Raw SQL export restricted under tenant isolation."}, status=403
                    )
                cols, rows, _ = _exec_conn_method(conn, "execute_raw", body["sql"], body.get("params") or [])
                export_data = {"rows": rows, "columns": cols}
            else:
                return JsonResponse({"error": "Missing export data source"}, status=400)

            content_bytes, mime_type, ext = export_dataset(export_data, format=fmt)
            resp = HttpResponse(content_bytes, content_type=mime_type)
            resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
            return resp
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=401)
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:
            return JsonResponse({"error": f"Export failed: {exc}"}, status=400)

    return [
        path("schema/", schema_view, name="query-builder-schema"),
        path("introspect/", schema_view, name="query-builder-introspect"),
        path("compile/", compile_view, name="query-builder-compile"),
        path("validate/", validate_view, name="query-builder-validate"),
        path("execute/", execute_view, name="query-builder-execute"),
        path("export/", export_view, name="query-builder-export"),
    ]


def create_drf_views(
    connector: Any,
    security: SecurityPolicy | dict[str, Any] | None = None,
    tenant_resolver: Callable[[DRFRequest], TenantContext | dict[str, Any] | str | None] | None = None,
) -> dict[str, type[APIView]]:
    """Generates Django REST Framework APIView classes for Query-Builder."""
    if not DRF_AVAILABLE:
        raise ImportError(
            "Django REST Framework is not installed. Install via 'pip install djangorestframework'."
        )

    policy = _get_effective_policy(security, tenant_resolver is not None)

    class SchemaView(APIView):
        def get(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            snapshot = _exec_conn_method(conn, "introspect_schema")
            data = _normalize_schema_snapshot(snapshot)
            data = _filter_schema_tables(data, policy)
            return DRFResponse(data)

    class CompileView(APIView):
        def post(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = request.data.get("spec")
            if not spec:
                raise ValidationError("Missing required 'spec'")
            active_spec = spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(spec, context=tenant_ctx, policy=policy)
            dialect = request.data.get("dialect") or getattr(conn, "dialect_name", "postgres")
            compiler = QueryCompiler(active_spec, schema=request.data.get("schema"), dialect=dialect)
            sql, params, c_sql, c_params = compiler.compile()
            return DRFResponse({
                "sql": sql,
                "params": params,
                "count_sql": c_sql,
                "count_params": c_params,
                "dialect": dialect,
            })

    class ValidateView(APIView):
        def post(self, request: DRFRequest) -> DRFResponse:
            sql = request.data.get("sql")
            if not sql:
                raise ValidationError("Missing required 'sql'")
            res = validate_sql_ast(sql, allowed_schemas=request.data.get("allowed_schemas"))
            return DRFResponse(res)

    class ExecuteView(APIView):
        def post(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = request.data.get("spec") or request.data.get("query")
            sql = request.data.get("sql")
            if not spec and not sql:
                raise ValidationError("Either 'spec' or 'sql' must be provided")

            if spec is not None:
                active_spec = spec
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(spec, context=tenant_ctx, policy=policy)
                res = _exec_conn_method(conn, "execute", active_spec, statement_timeout_ms=request.data.get("timeout_ms"))
                return DRFResponse(res.to_dict() if hasattr(res, "to_dict") else res)

            if policy and getattr(policy, "enforce_tenant_isolation", False):
                raise PermissionDenied("Raw SQL execution restricted under tenant isolation.")

            cols, rows, latency = _exec_conn_method(conn, "execute_raw", sql, request.data.get("params") or [])
            return DRFResponse({
                "columns": cols,
                "rows": rows,
                "count": len(rows),
                "latency_ms": round(latency, 2),
                "dialect": getattr(conn, "dialect_name", "sqlite"),
                "sql": sql,
            })

    class ExportView(APIView):
        def post(self, request: DRFRequest) -> HttpResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            fmt = request.data.get("format", "csv")
            if request.data.get("rows") is not None:
                export_data = {"rows": request.data["rows"], "columns": request.data.get("columns", [])}
            elif request.data.get("spec") is not None:
                active_spec = request.data["spec"]
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(active_spec, context=tenant_ctx, policy=policy)
                res = _exec_conn_method(conn, "execute", active_spec)
                export_data = {
                    "rows": res.get("rows", []) if isinstance(res, dict) else getattr(res, "rows", []),
                    "columns": res.get("columns", []) if isinstance(res, dict) else getattr(res, "columns", []),
                }
            elif request.data.get("sql") is not None:
                if policy and getattr(policy, "enforce_tenant_isolation", False):
                    raise PermissionDenied("Raw SQL export restricted under tenant isolation.")
                cols, rows, _ = _exec_conn_method(conn, "execute_raw", request.data["sql"], request.data.get("params") or [])
                export_data = {"rows": rows, "columns": cols}
            else:
                raise ValidationError("Missing export data source")

            content, mime, ext = export_dataset(export_data, format=fmt)
            resp = HttpResponse(content, content_type=mime)
            resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
            return resp

    return {
        "SchemaView": SchemaView,
        "CompileView": CompileView,
        "ValidateView": ValidateView,
        "ExecuteView": ExecuteView,
        "ExportView": ExportView,
    }


def create_ninja_router(
    connector: Any,
    security: SecurityPolicy | dict[str, Any] | None = None,
    tenant_resolver: Callable[[Any], TenantContext | dict[str, Any] | str | None] | None = None,
    tags: list[str] | None = None,
) -> Any:
    """Generates a Django Ninja Router for Query-Builder."""
    if not NINJA_AVAILABLE:
        raise ImportError(
            "Django Ninja is not installed. Install via 'pip install django-ninja' to use create_ninja_router."
        )

    router = NinjaRouter(tags=tags or ["Query Builder"])
    policy = _get_effective_policy(security, tenant_resolver is not None)

    @router.get("/schema")
    def get_schema(request: HttpRequest) -> dict[str, Any]:
        conn = _resolve_conn(connector)
        snapshot = _exec_conn_method(conn, "introspect_schema")
        data = _normalize_schema_snapshot(snapshot)
        return _filter_schema_tables(data, policy)

    @router.post("/compile")
    def compile_query(request: HttpRequest, payload: dict[str, Any]) -> dict[str, Any]:
        conn = _resolve_conn(connector)
        tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
        spec = payload.get("spec")
        if not spec:
            raise HttpError(400, "Missing required 'spec'")
        active_spec = spec
        if policy is not None or tenant_ctx is not None:
            active_spec = apply_security_policy(spec, context=tenant_ctx, policy=policy)
        dialect = payload.get("dialect") or getattr(conn, "dialect_name", "postgres")
        compiler = QueryCompiler(active_spec, schema=payload.get("schema"), dialect=dialect)
        sql, params, c_sql, c_params = compiler.compile()
        return {
            "sql": sql,
            "params": params,
            "count_sql": c_sql,
            "count_params": c_params,
            "dialect": dialect,
        }

    @router.post("/validate")
    def validate_query(request: HttpRequest, payload: dict[str, Any]) -> dict[str, Any]:
        sql = payload.get("sql")
        if not sql:
            raise HttpError(400, "Missing required 'sql'")
        return validate_sql_ast(sql, allowed_schemas=payload.get("allowed_schemas"))

    @router.post("/execute")
    def execute_query(request: HttpRequest, payload: dict[str, Any]) -> dict[str, Any]:
        conn = _resolve_conn(connector)
        tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
        spec = payload.get("spec") or payload.get("query")
        sql = payload.get("sql")
        if not spec and not sql:
            raise HttpError(400, "Either 'spec' or 'sql' must be provided")

        if spec is not None:
            active_spec = spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(spec, context=tenant_ctx, policy=policy)
            res = _exec_conn_method(conn, "execute", active_spec, statement_timeout_ms=payload.get("timeout_ms"))
            return res.to_dict() if hasattr(res, "to_dict") else res

        if policy and getattr(policy, "enforce_tenant_isolation", False):
            raise HttpError(403, "Raw SQL execution restricted under tenant isolation.")

        cols, rows, latency = _exec_conn_method(conn, "execute_raw", sql, payload.get("params") or [])
        return {
            "columns": cols,
            "rows": rows,
            "count": len(rows),
            "latency_ms": round(latency, 2),
            "dialect": getattr(conn, "dialect_name", "sqlite"),
            "sql": sql,
        }

    @router.post("/export")
    def export_query(request: HttpRequest, payload: dict[str, Any]) -> HttpResponse:
        conn = _resolve_conn(connector)
        tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
        fmt = payload.get("format", "csv")

        if payload.get("rows") is not None:
            export_data = {"rows": payload["rows"], "columns": payload.get("columns", [])}
        elif payload.get("spec") is not None:
            active_spec = payload["spec"]
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(active_spec, context=tenant_ctx, policy=policy)
            res = _exec_conn_method(conn, "execute", active_spec)
            export_data = {
                "rows": res.get("rows", []) if isinstance(res, dict) else getattr(res, "rows", []),
                "columns": res.get("columns", []) if isinstance(res, dict) else getattr(res, "columns", []),
            }
        elif payload.get("sql") is not None:
            if policy and getattr(policy, "enforce_tenant_isolation", False):
                raise HttpError(403, "Raw SQL export restricted under tenant isolation.")
            cols, rows, _ = _exec_conn_method(conn, "execute_raw", payload["sql"], payload.get("params") or [])
            export_data = {"rows": rows, "columns": cols}
        else:
            raise HttpError(400, "Missing export data source")

        content_bytes, mime_type, ext = export_dataset(export_data, format=fmt)
        resp = HttpResponse(content_bytes, content_type=mime_type)
        resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
        return resp

    return router
