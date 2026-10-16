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
from collections.abc import Callable, Coroutine
from dataclasses import asdict, is_dataclass, replace
from typing import Any, cast

from query_builder.advisor import analyze_query_performance, recommend_indexes
from query_builder.ast_validator import validate_sql_ast
from query_builder.capabilities import (
    DisabledFeatureError,
    EngineCapabilities,
    disabled_feature_message,
)
from query_builder.compiler import QueryCompiler
from query_builder.config import SecurityConfig
from query_builder.connectors.registry import get_connector
from query_builder.explain import estimate_plan_from_spec
from query_builder.export import (
    EXTENSIONS,
    MIME_TYPES,
    export_dataset,
    stream_export_dataset,
)
from query_builder.integrations._errors import public_error
from query_builder.join_solver import find_join_path
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.security import SecurityError

# Guarded imports
try:
    import django  # noqa: F401
    from django.http import (
        HttpRequest,
        HttpResponse,
        JsonResponse,
        StreamingHttpResponse,
    )
    from django.urls import path
    from django.views.decorators.csrf import csrf_exempt

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    HttpRequest = Any
    HttpResponse = Any
    JsonResponse = Any
    StreamingHttpResponse = Any

APIView = object
DRFRequest = Any
DRFResponse = Any


def _get_drf() -> tuple[type[Exception], type[Exception], Any, Any, Any]:
    try:
        import rest_framework  # noqa: F401
        from rest_framework.exceptions import PermissionDenied, ValidationError
        from rest_framework.request import Request as DRFReq
        from rest_framework.response import Response as DRFResp
        from rest_framework.views import APIView as DRFAPIView

        return PermissionDenied, ValidationError, DRFReq, DRFResp, DRFAPIView
    except ImportError as exc:
        raise ImportError(
            "Django REST Framework is not installed. Install via 'pip install djangorestframework'."
        ) from exc
    except Exception as exc:
        raise ImportError(
            f"Django REST Framework could not be loaded: {exc}. Ensure Django settings are configured."
        ) from exc


try:
    import importlib.util

    _ninja_spec = importlib.util.find_spec("ninja")
    NINJA_AVAILABLE = _ninja_spec is not None
except Exception:  # noqa: BLE001
    NINJA_AVAILABLE = False


# Kept as a module-level alias for type hints; the real class is imported lazily by
# `_get_ninja()` so importing this module never requires (or configures) django-ninja.
NinjaRouter = Any


def _get_ninja() -> tuple[type[Any], type[Exception]]:
    try:
        import ninja  # noqa: F401
        from ninja import Router as NinjaRouter
        from ninja.errors import HttpError

        return NinjaRouter, HttpError
    except ImportError as exc:
        raise ImportError(
            "Django Ninja is not installed. Install via 'pip install django-ninja' to use create_ninja_router."
        ) from exc
    except Exception as exc:
        raise ImportError(
            f"Django Ninja could not be loaded: {exc}. Ensure Django settings are configured."
        ) from exc


def _resolve_conn(connector: Any) -> Any:
    """Resolves connector from instance, factory callable, or name string."""
    if isinstance(connector, str):
        return get_connector(connector)
    if callable(connector) and not hasattr(connector, "execute"):
        res = connector()
        if inspect.isawaitable(res):
            import asyncio
            import concurrent.futures

            coro = cast("Coroutine[Any, Any, Any]", res)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, coro).result()
            else:
                return asyncio.run(coro)
        return res
    return connector


def _exec_conn_method(conn: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Executes a connector method supporting both synchronous and asynchronous connectors safely."""
    method = getattr(conn, method_name)
    call_kwargs = dict(kwargs)
    if (
        "statement_timeout_ms" in call_kwargs
        and call_kwargs["statement_timeout_ms"] is None
    ):
        call_kwargs.pop("statement_timeout_ms")
    elif "statement_timeout_ms" in call_kwargs:
        try:
            sig = inspect.signature(method)
            has_var_kwargs = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
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

        coro = cast("Coroutine[Any, Any, Any]", res)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)
    return res


def _filter_schema_tables(
    data: dict[str, Any], policy: SecurityPolicy | None
) -> dict[str, Any]:
    """Filters schema snapshot tables according to policy allow/restricted lists."""
    if policy and "tables" in data and isinstance(data["tables"], dict):
        allowed = (
            set(policy.allowed_tables) if policy.allowed_tables is not None else None
        )
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
    except Exception:  # noqa: BLE001
        return {"tables": {}}


class TenantResolutionError(PermissionError):
    """Raised when the request's tenant cannot be resolved (a deliberate 401)."""


def _stream_download(stream_iter: Any, fmt: Any) -> Any:
    """A streamed file download whose headers come only from the fixed export tables.

    The content type and file name are looked up from constants (never echoed from the
    request), the body is a download, and sniffing is switched off, so exported cell
    text is never interpreted as a page.
    """
    key = fmt.strip().lower() if isinstance(fmt, str) else ""
    mime, ext = "application/octet-stream", "bin"
    for name, known_mime in MIME_TYPES.items():
        if name == key:
            mime, ext = known_mime, EXTENSIONS[name]
    resp = StreamingHttpResponse(stream_iter, content_type=mime)
    resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def _unauthorized_message(exc: PermissionError) -> str:
    """Client text for a 401: our own wording, never an OS error's text (it can hold a path)."""
    if isinstance(exc, TenantResolutionError):
        return str(exc)
    return "Unauthorized."


def _resolve_tenant_sync(
    request: Any,
    tenant_resolver: Callable[[Any], TenantContext | dict[str, Any] | str | None]
    | None,
) -> TenantContext | None:
    """Resolves tenant context synchronously, failing closed if configured."""
    if tenant_resolver is None:
        return None

    res = tenant_resolver(request)
    if inspect.isawaitable(res):
        import asyncio
        import concurrent.futures

        coro = cast("Coroutine[Any, Any, Any]", res)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                res = pool.submit(asyncio.run, coro).result()
        else:
            res = asyncio.run(coro)

    if res is None:
        raise TenantResolutionError(
            "Unauthorized: TenantContext could not be resolved from request."
        )

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
        raise TenantResolutionError(
            f"Unauthorized: Invalid tenant context type '{type(res).__name__}'."
        )

    if not ctx.tenant_id or not str(ctx.tenant_id).strip():
        raise TenantResolutionError(
            "Unauthorized: Resolved TenantContext contains empty tenant_id."
        )

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
            return replace(security, enforce_tenant_isolation=True)
        return security
    if isinstance(security, dict):
        pol = SecurityPolicy(**security)
        if has_tenant_resolver:
            pol.enforce_tenant_isolation = True
        return pol
    if hasattr(security, "privacy"):
        # SecurityConfig instance
        pol = SecurityPolicy(
            allowed_tables=getattr(
                getattr(security, "privacy", None), "allowed_tables", None
            ),
            restricted_tables=getattr(
                getattr(security, "privacy", None), "restricted_tables", []
            ),
            tenant_column=getattr(security.privacy, "tenant_column", "tenant_id"),
            enforce_tenant_isolation=True
            if has_tenant_resolver
            else getattr(security.privacy, "enforce_tenant_isolation", False),
            sensitive_column_patterns=getattr(
                security.privacy, "sensitive_column_patterns", []
            ),
            masking_strategy=getattr(security.privacy, "masking_strategy", "redact"),
            max_complexity_score=getattr(
                security.execution, "max_complexity_score", None
            )
            if hasattr(security, "execution")
            else None,
        )
        return pol
    # Duck-typed policy object (neither SecurityConfig nor dict): passed through as-is.
    return cast("SecurityPolicy | None", security)


def _is_tenant_isolation_active(
    policy: Any,
    tenant_ctx: Any,
    payload_or_body: Any,
) -> bool:
    """Returns True if tenant isolation is enforced via policy, resolved context, or request body."""
    if policy and getattr(policy, "enforce_tenant_isolation", False):
        return True
    if tenant_ctx is not None:
        return True
    if not isinstance(payload_or_body, dict):
        return False
    if payload_or_body.get("tenant_id"):
        return True
    ctx = payload_or_body.get("context")
    if isinstance(ctx, dict) and ctx.get("tenant_id"):
        return True
    if getattr(ctx, "tenant_id", None):
        return True
    pol = payload_or_body.get("policy")
    if isinstance(pol, dict) and pol.get("enforce_tenant_isolation"):
        return True
    if getattr(pol, "enforce_tenant_isolation", False):
        return True
    return False


def create_django_urls(
    connector: Any,
    security: SecurityPolicy | dict[str, Any] | None = None,
    tenant_resolver: Callable[
        [HttpRequest], TenantContext | dict[str, Any] | str | None
    ]
    | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    schema_cache_ttl: float = 0.0,
    ai_provider: Any = None,
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
    capabilities:
        Engine capabilities or dictionary defining enabled/advanced/disabled features.
    schema_cache_ttl:
        Time-to-live in seconds for cached schema introspection. Defaults to 0.0 (disabled).

    Returns
    -------
    list of django.urls.path
    """
    if not DJANGO_AVAILABLE:
        raise ImportError(
            "Django is not installed. Install it via 'pip install django' to use create_django_urls."
        )

    import time

    cached_schema_data: dict[str, Any] | None = None
    cached_schema_time: float = 0.0

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

    @csrf_exempt
    def capabilities_view(request: HttpRequest) -> HttpResponse:
        if request.method != "GET":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        return JsonResponse({"capabilities": effective_capabilities.to_dict()})

    @csrf_exempt
    def schema_view(request: HttpRequest) -> HttpResponse:
        if request.method != "GET":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        nonlocal cached_schema_data, cached_schema_time
        refresh = request.GET.get("refresh", "").lower() in ("true", "1")
        if (
            not refresh
            and schema_cache_ttl > 0.0
            and cached_schema_data is not None
            and (time.monotonic() - cached_schema_time) < schema_cache_ttl
        ):
            return JsonResponse(cached_schema_data, safe=False)

        conn = _resolve_conn(connector)
        try:
            snapshot = _exec_conn_method(conn, "introspect_schema")
            data = _normalize_schema_snapshot(snapshot)
            data["capabilities"] = effective_capabilities.to_dict()
            data = _filter_schema_tables(data, policy)
            if schema_cache_ttl > 0.0:
                cached_schema_data = dict(data)
                cached_schema_time = time.monotonic()
            return JsonResponse(data, safe=False)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Schema introspection failed", exc)}, status=500
            )

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
                return JsonResponse(
                    {"error": f"Security violation: {'; '.join(violations)}"},
                    status=403,
                )
            return JsonResponse(
                {
                    "sql": main_sql,
                    "params": params,
                    "count_sql": count_sql,
                    "count_params": count_params,
                    "dialect": dialect,
                }
            )
        except PermissionError as exc:
            return JsonResponse({"error": _unauthorized_message(exc)}, status=401)
        except DisabledFeatureError as exc:
            return JsonResponse(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Compilation failed", exc)}, status=400
            )

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
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Validation failed", exc)}, status=400
            )

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
                return JsonResponse(
                    {"error": "Either 'spec' or 'sql' must be provided"}, status=400
                )

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

                active_spec = spec
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(
                        spec,
                        schema=body.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )
                result = _exec_conn_method(
                    conn,
                    "execute",
                    active_spec,
                    statement_timeout_ms=body.get("timeout_ms"),
                )
                if hasattr(result, "to_dict"):
                    return JsonResponse(result.to_dict(), safe=False)
                if isinstance(result, dict):
                    return JsonResponse(result, safe=False)
                return JsonResponse(
                    {
                        "columns": getattr(result, "columns", []),
                        "rows": getattr(result, "rows", []),
                        "count": len(getattr(result, "rows", [])),
                        "latency_ms": getattr(result, "latency_ms", 0.0),
                        "dialect": getattr(conn, "dialect_name", "sqlite"),
                        "sql": getattr(result, "sql", ""),
                    }
                )

            if not effective_capabilities.is_enabled("raw_sql"):
                return JsonResponse(
                    {"error": "Feature 'raw_sql' is disabled in engine capabilities."},
                    status=403,
                )

            if _is_tenant_isolation_active(policy, tenant_ctx, body):
                return JsonResponse(
                    {"error": "Raw SQL execution restricted under tenant isolation."},
                    status=403,
                )

            if not isinstance(sql, str):
                return JsonResponse({"error": "'sql' must be a string"}, status=400)

            val_res = validate_sql_ast(sql, allowed_schemas=body.get("allowed_schemas"))
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                return JsonResponse(
                    {"error": f"Security violation: {'; '.join(violations)}"},
                    status=403,
                )

            cols, rows, latency = _exec_conn_method(
                conn, "execute_raw", sql, body.get("params") or []
            )
            return JsonResponse(
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
            return JsonResponse({"error": _unauthorized_message(exc)}, status=401)
        except DisabledFeatureError as exc:
            return JsonResponse(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Execution failed", exc)}, status=400
            )

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
                    active_spec = apply_security_policy(
                        active_spec,
                        schema=body.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )
                res = _exec_conn_method(conn, "execute", active_spec)
                export_data = {
                    "rows": res.get("rows", [])
                    if isinstance(res, dict)
                    else getattr(res, "rows", []),
                    "columns": res.get("columns", [])
                    if isinstance(res, dict)
                    else getattr(res, "columns", []),
                }
            elif body.get("sql") is not None:
                if not effective_capabilities.is_enabled("raw_sql"):
                    return JsonResponse(
                        {
                            "error": "Feature 'raw_sql' is disabled in engine capabilities."
                        },
                        status=403,
                    )
                if _is_tenant_isolation_active(policy, tenant_ctx, body):
                    return JsonResponse(
                        {"error": "Raw SQL export restricted under tenant isolation."},
                        status=403,
                    )
                val_res = validate_sql_ast(
                    body["sql"], allowed_schemas=body.get("allowed_schemas")
                )
                if not val_res.get("valid") or not val_res.get("is_read_only"):
                    violations = val_res.get(
                        "violations", ["Query failed AST safety validation."]
                    )
                    return JsonResponse(
                        {"error": f"Security violation: {'; '.join(violations)}"},
                        status=403,
                    )
                cols, rows, _ = _exec_conn_method(
                    conn, "execute_raw", body["sql"], body.get("params") or []
                )
                export_data = {"rows": rows, "columns": cols}
            else:
                return JsonResponse({"error": "Missing export data source"}, status=400)

            if body.get("stream", False):
                return export_stream_view(request)

            content_bytes, mime_type, ext = export_dataset(export_data, format=fmt)
            resp = HttpResponse(content_bytes, content_type=mime_type)
            resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
            return resp
        except PermissionError as exc:
            return JsonResponse({"error": _unauthorized_message(exc)}, status=401)
        except DisabledFeatureError as exc:
            return JsonResponse(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Export failed", exc)}, status=400
            )

    @csrf_exempt
    def export_stream_view(request: HttpRequest) -> HttpResponse:
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
                    active_spec = apply_security_policy(
                        active_spec,
                        schema=body.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )
                res = _exec_conn_method(conn, "execute", active_spec)
                export_data = {
                    "rows": res.get("rows", [])
                    if isinstance(res, dict)
                    else getattr(res, "rows", []),
                    "columns": res.get("columns", [])
                    if isinstance(res, dict)
                    else getattr(res, "columns", []),
                }
            elif body.get("sql") is not None:
                if not effective_capabilities.is_enabled("raw_sql"):
                    return JsonResponse(
                        {
                            "error": "Feature 'raw_sql' is disabled in engine capabilities."
                        },
                        status=403,
                    )
                if _is_tenant_isolation_active(policy, tenant_ctx, body):
                    return JsonResponse(
                        {"error": "Raw SQL export restricted under tenant isolation."},
                        status=403,
                    )
                val_res = validate_sql_ast(
                    body["sql"], allowed_schemas=body.get("allowed_schemas")
                )
                if not val_res.get("valid") or not val_res.get("is_read_only"):
                    violations = val_res.get(
                        "violations", ["Query failed AST safety validation."]
                    )
                    return JsonResponse(
                        {"error": f"Security violation: {'; '.join(violations)}"},
                        status=403,
                    )
                cols, rows, _ = _exec_conn_method(
                    conn, "execute_raw", body["sql"], body.get("params") or []
                )
                export_data = {"rows": rows, "columns": cols}
            else:
                return JsonResponse({"error": "Missing export data source"}, status=400)

            stream_iter, _mime, _ext = stream_export_dataset(export_data, format=fmt)
            resp = _stream_download(stream_iter, fmt)
            return resp
        except PermissionError as exc:
            return JsonResponse({"error": _unauthorized_message(exc)}, status=401)
        except DisabledFeatureError as exc:
            return JsonResponse(
                {"error": disabled_feature_message(exc, effective_capabilities)},
                status=403,
            )
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Streaming export failed", exc)}, status=400
            )

    @csrf_exempt
    def explain_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        conn = _resolve_conn(connector)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            target_spec = body.get("spec") or body.get("query")
            if (
                not target_spec
                or not isinstance(target_spec, dict)
                or not target_spec.get("table")
            ):
                return JsonResponse(
                    {"error": "Missing required 'table' in query specification."},
                    status=400,
                )
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            active_spec = target_spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    target_spec,
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
            sql, params = compiler.compile()[0:2]
            plan = estimate_plan_from_spec(active_spec, schema=body.get("schema"))
            perf = analyze_query_performance(
                active_spec, sql=sql, dialect=str(dialect or "postgres")
            )
            rec_indexes = recommend_indexes(active_spec)
            return JsonResponse(
                {
                    "sql": sql,
                    "params": params,
                    "dialect": dialect,
                    "plan": plan.to_dict() if hasattr(plan, "to_dict") else plan,
                    "performance": perf,
                    "recommended_indexes": rec_indexes,
                },
                safe=False,
            )
        except PermissionError as exc:
            return JsonResponse({"error": _unauthorized_message(exc)}, status=401)
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Explain failed", exc)}, status=400
            )

    @csrf_exempt
    def join_path_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            active_tables = body.get("active_tables", [])
            target_table = body.get("target_table", "")
            if not active_tables or not target_table:
                return JsonResponse(
                    {"error": "Both 'active_tables' and 'target_table' are required."},
                    status=400,
                )
            schema_data = body.get("schema")
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
            return JsonResponse(
                {
                    "path": path_steps,
                    "connected": bool(path_steps),
                    "target_table": target_table,
                },
                safe=False,
            )
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("Join path solver failed", exc)}, status=400
            )

    @csrf_exempt
    def nlq_view(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                return JsonResponse({"error": "Prompt must not be empty."}, status=400)

            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            schema_data = body.get("schema")
            if schema_data is None:
                raw_schema = _exec_conn_method(conn, "introspect_schema")
                schema_data = _normalize_schema_snapshot(raw_schema)
            schema_data = _filter_schema_tables(schema_data, policy)

            dialect_str = str(
                body.get("dialect")
                or getattr(conn, "dialect_name", "postgres")
                or "postgres"
            )
            from query_builder.ai.client import ask_ai

            ai_res = ask_ai(
                prompt=prompt,
                ai=ai_provider,
                schema=schema_data,
                dialect=dialect_str,
                options=body.get("options"),
            )
            raw_spec = dict(ai_res.spec)
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
            return JsonResponse(
                {
                    "spec": raw_spec,
                    "sql": final_sql,
                    "params": final_params,
                    "explanation": ai_res.explanation,
                    "confidence": ai_res.confidence,
                    "warnings": ai_res.warnings,
                },
                safe=False,
            )
        except SecurityError as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except Exception as exc:  # noqa: BLE001
            return JsonResponse(
                {"error": public_error("NLQ translation failed", exc)}, status=400
            )

    return [
        path("schema/", schema_view, name="query-builder-schema"),
        path("introspect/", schema_view, name="query-builder-introspect"),
        path("capabilities/", capabilities_view, name="query-builder-capabilities"),
        path("compile/", compile_view, name="query-builder-compile"),
        path("validate/", validate_view, name="query-builder-validate"),
        path("execute/", execute_view, name="query-builder-execute"),
        path("export/", export_view, name="query-builder-export"),
        path("export/stream/", export_stream_view, name="query-builder-export-stream"),
        path("explain/", explain_view, name="query-builder-explain"),
        path("join-path/", join_path_view, name="query-builder-join-path"),
        path("nlq/", nlq_view, name="query-builder-nlq"),
    ]


def create_drf_views(
    connector: Any,
    security: SecurityPolicy | dict[str, Any] | None = None,
    tenant_resolver: Callable[[DRFRequest], TenantContext | dict[str, Any] | str | None]
    | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    ai_provider: Any = None,
) -> dict[str, type[APIView]]:
    """Generates Django REST Framework APIView classes for Query-Builder."""
    PermissionDenied, ValidationError, _, drf_response, drf_api_view = _get_drf()

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

    class CapabilitiesView(drf_api_view):  # type: ignore[misc, valid-type]  # dynamic DRF base class
        def get(self, request: DRFRequest) -> DRFResponse:
            return drf_response({"capabilities": effective_capabilities.to_dict()})

    class SchemaView(drf_api_view):  # type: ignore[misc, valid-type]  # dynamic DRF base class
        def get(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            snapshot = _exec_conn_method(conn, "introspect_schema")
            data = _normalize_schema_snapshot(snapshot)
            data["capabilities"] = effective_capabilities.to_dict()
            data = _filter_schema_tables(data, policy)
            return drf_response(data)

    class CompileView(drf_api_view):  # type: ignore[misc, valid-type]  # dynamic DRF base class
        def post(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = request.data.get("spec")
            if not spec:
                raise ValidationError("Missing required 'spec'")
            active_spec = spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    spec, context=tenant_ctx, policy=policy
                )
            dialect = request.data.get("dialect") or getattr(
                conn, "dialect_name", "postgres"
            )
            try:
                compiler = QueryCompiler(
                    active_spec,
                    schema=request.data.get("schema"),
                    dialect=dialect,
                    capabilities=effective_capabilities,
                )
                sql, params, c_sql, c_params = compiler.compile()
                val_res = validate_sql_ast(sql, dialect=dialect)
                if not val_res.get("valid") or not val_res.get("is_read_only"):
                    violations = val_res.get(
                        "violations", ["Query failed AST safety validation."]
                    )
                    raise PermissionDenied(
                        f"Security violation: {'; '.join(violations)}"
                    )
            except DisabledFeatureError as exc:
                raise PermissionDenied(
                    disabled_feature_message(exc, effective_capabilities)
                ) from exc
            return drf_response(
                {
                    "sql": sql,
                    "params": params,
                    "count_sql": c_sql,
                    "count_params": c_params,
                    "dialect": dialect,
                }
            )

    class ValidateView(drf_api_view):  # type: ignore[misc, valid-type]  # dynamic DRF base class
        def post(self, request: DRFRequest) -> DRFResponse:
            sql = request.data.get("sql")
            if not sql:
                raise ValidationError("Missing required 'sql'")
            res = validate_sql_ast(
                sql, allowed_schemas=request.data.get("allowed_schemas")
            )
            return drf_response(res)

    class ExecuteView(drf_api_view):  # type: ignore[misc, valid-type]  # dynamic DRF base class
        def post(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            spec = request.data.get("spec") or request.data.get("query")
            sql = request.data.get("sql")
            if not spec and not sql:
                raise ValidationError("Either 'spec' or 'sql' must be provided")

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

                active_spec = spec
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(
                        spec,
                        schema=request.data.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )
                res = _exec_conn_method(
                    conn,
                    "execute",
                    active_spec,
                    statement_timeout_ms=request.data.get("timeout_ms"),
                )
                return drf_response(res.to_dict() if hasattr(res, "to_dict") else res)

            if not effective_capabilities.is_enabled("raw_sql"):
                raise PermissionDenied(
                    "Feature 'raw_sql' is disabled in engine capabilities."
                )

            if _is_tenant_isolation_active(policy, tenant_ctx, request.data):
                raise PermissionDenied(
                    "Raw SQL execution restricted under tenant isolation."
                )

            val_res = validate_sql_ast(
                sql, allowed_schemas=request.data.get("allowed_schemas")
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise PermissionDenied(f"Security violation: {'; '.join(violations)}")

            cols, rows, latency = _exec_conn_method(
                conn, "execute_raw", sql, request.data.get("params") or []
            )
            return drf_response(
                {
                    "columns": cols,
                    "rows": rows,
                    "count": len(rows),
                    "latency_ms": round(latency, 2),
                    "dialect": getattr(conn, "dialect_name", "sqlite"),
                    "sql": sql,
                }
            )

    class ExportView(drf_api_view):  # type: ignore[misc, valid-type]  # dynamic DRF base class
        def post(self, request: DRFRequest) -> HttpResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            fmt = request.data.get("format", "csv")
            if request.data.get("rows") is not None:
                export_data = {
                    "rows": request.data["rows"],
                    "columns": request.data.get("columns", []),
                }
            elif request.data.get("spec") is not None:
                active_spec = request.data["spec"]
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(
                        active_spec,
                        schema=request.data.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )
                res = _exec_conn_method(conn, "execute", active_spec)
                export_data = {
                    "rows": res.get("rows", [])
                    if isinstance(res, dict)
                    else getattr(res, "rows", []),
                    "columns": res.get("columns", [])
                    if isinstance(res, dict)
                    else getattr(res, "columns", []),
                }
            elif request.data.get("sql") is not None:
                if not effective_capabilities.is_enabled("raw_sql"):
                    raise PermissionDenied(
                        "Feature 'raw_sql' is disabled in engine capabilities."
                    )
                if _is_tenant_isolation_active(policy, tenant_ctx, request.data):
                    raise PermissionDenied(
                        "Raw SQL export restricted under tenant isolation."
                    )
                val_res = validate_sql_ast(
                    request.data["sql"],
                    allowed_schemas=request.data.get("allowed_schemas"),
                )
                if not val_res.get("valid") or not val_res.get("is_read_only"):
                    violations = val_res.get(
                        "violations", ["Query failed AST safety validation."]
                    )
                    raise PermissionDenied(
                        f"Security violation: {'; '.join(violations)}"
                    )
                cols, rows, _ = _exec_conn_method(
                    conn,
                    "execute_raw",
                    request.data["sql"],
                    request.data.get("params") or [],
                )
                export_data = {"rows": rows, "columns": cols}
            else:
                raise ValidationError("Missing export data source")

            if request.data.get("stream", False):
                stream_iter, _mime, _ext = stream_export_dataset(
                    export_data, format=fmt
                )
                resp = _stream_download(stream_iter, fmt)
                return resp

            content, mime, ext = export_dataset(export_data, format=fmt)
            resp = HttpResponse(content, content_type=mime)
            resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
            return resp

    class ExportStreamView(drf_api_view):  # type: ignore[misc, valid-type]
        def post(self, request: DRFRequest) -> HttpResponse:
            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            fmt = request.data.get("format", "csv")

            if request.data.get("rows") is not None:
                export_data = {
                    "rows": request.data["rows"],
                    "columns": request.data.get("columns", []),
                }
            elif request.data.get("spec") is not None:
                active_spec = request.data["spec"]
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(
                        active_spec,
                        schema=request.data.get("schema"),
                        context=tenant_ctx,
                        policy=policy,
                    )
                res = _exec_conn_method(conn, "execute", active_spec)
                export_data = {
                    "rows": res.get("rows", [])
                    if isinstance(res, dict)
                    else getattr(res, "rows", []),
                    "columns": res.get("columns", [])
                    if isinstance(res, dict)
                    else getattr(res, "columns", []),
                }
            elif request.data.get("sql") is not None:
                if not effective_capabilities.is_enabled("raw_sql"):
                    raise PermissionDenied(
                        "Feature 'raw_sql' is disabled in engine capabilities."
                    )
                if _is_tenant_isolation_active(policy, tenant_ctx, request.data):
                    raise PermissionDenied(
                        "Raw SQL export restricted under tenant isolation."
                    )
                val_res = validate_sql_ast(
                    request.data["sql"],
                    allowed_schemas=request.data.get("allowed_schemas"),
                )
                if not val_res.get("valid") or not val_res.get("is_read_only"):
                    violations = val_res.get(
                        "violations", ["Query failed AST safety validation."]
                    )
                    raise PermissionDenied(
                        f"Security violation: {'; '.join(violations)}"
                    )
                cols, rows, _ = _exec_conn_method(
                    conn,
                    "execute_raw",
                    request.data["sql"],
                    request.data.get("params") or [],
                )
                export_data = {"rows": rows, "columns": cols}
            else:
                raise ValidationError("Missing export data source")

            stream_iter, _mime, _ext = stream_export_dataset(export_data, format=fmt)
            resp = _stream_download(stream_iter, fmt)
            return resp

    class ExplainView(drf_api_view):  # type: ignore[misc, valid-type]
        def post(self, request: DRFRequest) -> DRFResponse:
            conn = _resolve_conn(connector)
            target_spec = request.data.get("spec") or request.data.get("query")
            if (
                not target_spec
                or not isinstance(target_spec, dict)
                or not target_spec.get("table")
            ):
                raise ValidationError(
                    "Missing required 'table' in query specification."
                )
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            active_spec = target_spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    target_spec,
                    schema=request.data.get("schema"),
                    context=tenant_ctx,
                    policy=policy,
                )

            dialect = request.data.get("dialect") or getattr(
                conn, "dialect_name", "postgres"
            )
            compiler = QueryCompiler(
                active_spec,
                schema=request.data.get("schema"),
                dialect=dialect,
                capabilities=effective_capabilities,
            )
            sql, params = compiler.compile()[0:2]
            plan = estimate_plan_from_spec(
                active_spec, schema=request.data.get("schema")
            )
            perf = analyze_query_performance(
                active_spec, sql=sql, dialect=str(dialect or "postgres")
            )
            rec_indexes = recommend_indexes(active_spec)
            return drf_response(
                {
                    "sql": sql,
                    "params": params,
                    "dialect": dialect,
                    "plan": plan.to_dict() if hasattr(plan, "to_dict") else plan,
                    "performance": perf,
                    "recommended_indexes": rec_indexes,
                }
            )

    class JoinPathView(drf_api_view):  # type: ignore[misc, valid-type]
        def post(self, request: DRFRequest) -> DRFResponse:
            active_tables = request.data.get("active_tables", [])
            target_table = request.data.get("target_table", "")
            if not active_tables or not target_table:
                raise ValidationError(
                    "Both 'active_tables' and 'target_table' are required."
                )
            schema_data = request.data.get("schema")
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
            return drf_response(
                {
                    "path": path_steps,
                    "connected": bool(path_steps),
                    "target_table": target_table,
                }
            )

    class NlqView(drf_api_view):  # type: ignore[misc, valid-type]
        def post(self, request: DRFRequest) -> DRFResponse:
            prompt = str(request.data.get("prompt", "")).strip()
            if not prompt:
                raise ValidationError("Prompt must not be empty.")

            conn = _resolve_conn(connector)
            tenant_ctx = _resolve_tenant_sync(request, tenant_resolver)
            schema_data = request.data.get("schema")
            if schema_data is None:
                raw_schema = _exec_conn_method(conn, "introspect_schema")
                schema_data = _normalize_schema_snapshot(raw_schema)
            schema_data = _filter_schema_tables(schema_data, policy)

            dialect_str = str(
                request.data.get("dialect")
                or getattr(conn, "dialect_name", "postgres")
                or "postgres"
            )
            from query_builder.ai.client import ask_ai

            ai_res = ask_ai(
                prompt=prompt,
                ai=ai_provider,
                schema=schema_data,
                dialect=dialect_str,
                options=request.data.get("options"),
            )
            raw_spec = dict(ai_res.spec)
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
            return drf_response(
                {
                    "spec": raw_spec,
                    "sql": final_sql,
                    "params": final_params,
                    "explanation": ai_res.explanation,
                    "confidence": ai_res.confidence,
                    "warnings": ai_res.warnings,
                }
            )

    return {
        "SchemaView": SchemaView,
        "CompileView": CompileView,
        "ValidateView": ValidateView,
        "ExecuteView": ExecuteView,
        "ExportView": ExportView,
        "CapabilitiesView": CapabilitiesView,
        "ExportStreamView": ExportStreamView,
        "ExplainView": ExplainView,
        "JoinPathView": JoinPathView,
        "NlqView": NlqView,
        "schema": SchemaView,
        "compile": CompileView,
        "validate": ValidateView,
        "execute": ExecuteView,
        "export": ExportView,
        "export_stream": ExportStreamView,
        "explain": ExplainView,
        "join_path": JoinPathView,
        "nlq": NlqView,
        "capabilities": CapabilitiesView,
    }


def create_ninja_router(
    connector: Any,
    security: SecurityPolicy | dict[str, Any] | None = None,
    tenant_resolver: Callable[[Any], TenantContext | dict[str, Any] | str | None]
    | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Any:
    """Generates a Django Ninja Router for Query-Builder."""
    if not NINJA_AVAILABLE:
        raise ImportError(
            "Django Ninja is not installed. Install via 'pip install django-ninja' to use create_ninja_router."
        )

    NinjaRouter, HttpError = _get_ninja()
    router = NinjaRouter(tags=tags or ["Query Builder"])
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

    @router.get("/capabilities")
    def get_capabilities(request: HttpRequest) -> dict[str, Any]:
        return {"capabilities": effective_capabilities.to_dict()}

    @router.get("/schema")
    def get_schema(request: HttpRequest) -> dict[str, Any]:
        conn = _resolve_conn(connector)
        snapshot = _exec_conn_method(conn, "introspect_schema")
        data = _normalize_schema_snapshot(snapshot)
        data["capabilities"] = effective_capabilities.to_dict()
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
        try:
            compiler = QueryCompiler(
                active_spec,
                schema=payload.get("schema"),
                dialect=dialect,
                capabilities=effective_capabilities,
            )
            sql, params, c_sql, c_params = compiler.compile()
            val_res = validate_sql_ast(sql, dialect=dialect)
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise HttpError(403, f"Security violation: {'; '.join(violations)}")
        except DisabledFeatureError as exc:
            raise HttpError(
                403, disabled_feature_message(exc, effective_capabilities)
            ) from exc
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

            active_spec = spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    spec, context=tenant_ctx, policy=policy
                )
            res = _exec_conn_method(
                conn,
                "execute",
                active_spec,
                statement_timeout_ms=payload.get("timeout_ms"),
            )
            return res.to_dict() if hasattr(res, "to_dict") else res

        if not isinstance(sql, str):
            raise HttpError(400, "'sql' must be a string")

        if not effective_capabilities.is_enabled("raw_sql"):
            raise HttpError(
                403, "Feature 'raw_sql' is disabled in engine capabilities."
            )

        if _is_tenant_isolation_active(policy, tenant_ctx, payload):
            raise HttpError(403, "Raw SQL execution restricted under tenant isolation.")

        val_res = validate_sql_ast(sql, allowed_schemas=payload.get("allowed_schemas"))
        if not val_res.get("valid") or not val_res.get("is_read_only"):
            violations = val_res.get(
                "violations", ["Query failed AST safety validation."]
            )
            raise HttpError(403, f"Security violation: {'; '.join(violations)}")

        cols, rows, latency = _exec_conn_method(
            conn, "execute_raw", sql, payload.get("params") or []
        )
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
            export_data = {
                "rows": payload["rows"],
                "columns": payload.get("columns", []),
            }
        elif payload.get("spec") is not None:
            active_spec = payload["spec"]
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    active_spec, context=tenant_ctx, policy=policy
                )
            res = _exec_conn_method(conn, "execute", active_spec)
            export_data = {
                "rows": res.get("rows", [])
                if isinstance(res, dict)
                else getattr(res, "rows", []),
                "columns": res.get("columns", [])
                if isinstance(res, dict)
                else getattr(res, "columns", []),
            }
        elif payload.get("sql") is not None:
            sql_val = payload["sql"]
            if not isinstance(sql_val, str):
                raise HttpError(400, "'sql' must be a string")
            if not effective_capabilities.is_enabled("raw_sql"):
                raise HttpError(
                    403, "Feature 'raw_sql' is disabled in engine capabilities."
                )
            if _is_tenant_isolation_active(policy, tenant_ctx, payload):
                raise HttpError(
                    403, "Raw SQL export restricted under tenant isolation."
                )
            val_res = validate_sql_ast(
                sql_val, allowed_schemas=payload.get("allowed_schemas")
            )
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise HttpError(403, f"Security violation: {'; '.join(violations)}")
            cols, rows, _ = _exec_conn_method(
                conn, "execute_raw", sql_val, payload.get("params") or []
            )
            export_data = {"rows": rows, "columns": cols}
        else:
            raise HttpError(400, "Missing export data source")

        content_bytes, mime_type, ext = export_dataset(export_data, format=fmt)
        resp = HttpResponse(content_bytes, content_type=mime_type)
        resp["Content-Disposition"] = f'attachment; filename="export.{ext}"'
        return resp

    return router
