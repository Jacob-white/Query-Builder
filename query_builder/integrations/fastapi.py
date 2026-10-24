"""
FastAPI Router Integration for Query-Builder.
==============================================
Turnkey production-ready APIRouter factory registering:
- GET  /schema      (and GET /introspect): Introspect database schema snapshot
- POST /compile     : Compile declarative QuerySpec to target dialect SQL
- POST /validate    : Validate arbitrary SQL AST safety and schema restrictions
- POST /execute     : Execute query specification or raw SQL against connector
- POST /export      : Multi-format export (CSV, JSON, Arrow, Parquet, Excel, TSV)

Security & Multi-Tenancy Architecture:
--------------------------------------
Enforces fail-closed multi-tenant row-level security (RLS) via `tenant_resolver`.
Unauthenticated tenant IDs from client bodies are strictly ignored to prevent
cross-tenant data leakage.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from typing import Any, cast

try:
    from fastapi import APIRouter, HTTPException, Query, Request, Response
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel, ConfigDict, Field

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    APIRouter = object
    HTTPException = Exception
    Request = Any
    Response = Any
    StreamingResponse = Any
    Query = Any
    BaseModel = object
    ConfigDict = dict

    def _field_fallback(*args: Any, **kwargs: Any) -> Any:
        return None

    Field = _field_fallback


from query_builder.advisor import analyze_query_performance, recommend_indexes
from query_builder.ast_validator import validate_sql_ast
from query_builder.capabilities import (
    DisabledFeatureError,
    EngineCapabilities,
    disabled_feature_message,
)
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.config import SecurityConfig
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.registry import get_connector
from query_builder.explain import estimate_plan_from_spec
from query_builder.export import ExportError, export_dataset, stream_export_dataset
from query_builder.integrations._errors import public_error
from query_builder.join_solver import find_join_path
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.security import SecurityError


class CompileRequest(BaseModel):
    """Request model for /compile endpoint."""

    spec: dict[str, Any] = Field(description="Declarative QuerySpec dictionary")
    schema_snapshot: dict[str, Any] | None = Field(
        default=None, alias="schema", description="Optional schema snapshot override"
    )
    dialect: str | None = Field(
        default=None,
        description="Target SQL dialect override (e.g. postgres, snowflake)",
    )
    policy: dict[str, Any] | None = Field(
        default=None, description="Optional ad-hoc security policy parameters"
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ValidateRequest(BaseModel):
    """Request model for /validate endpoint."""

    sql: str = Field(description="SQL query string to validate")
    allowed_schemas: list[str] | None = Field(
        default=None, description="Optional list of allowed database schemas"
    )

    model_config = ConfigDict(extra="allow")


class ExecuteRequest(BaseModel):
    """Request model for /execute endpoint."""

    spec: dict[str, Any] | None = Field(
        default=None, description="Declarative QuerySpec dictionary"
    )
    query: dict[str, Any] | None = Field(default=None, description="Alias for spec")
    sql: str | None = Field(
        default=None,
        description="Raw SQL statement (disallowed in strict multi-tenant mode)",
    )
    params: list[Any] | dict[str, Any] | None = Field(
        default=None, description="Bind parameters for raw SQL execution"
    )
    timeout_ms: int | float | None = Field(
        default=None, description="Statement timeout isolation in milliseconds"
    )
    limit: int | None = Field(default=None, description="Row limit ceiling")
    offset: int | None = Field(default=None, description="Row offset pagination")

    model_config = ConfigDict(extra="allow")


class ExplainRequest(BaseModel):
    """Request model for /explain endpoint."""

    spec: dict[str, Any] | None = Field(
        default=None, description="Declarative QuerySpec dictionary"
    )
    query: dict[str, Any] | None = Field(default=None, description="Alias for spec")
    schema_snapshot: dict[str, Any] | None = Field(
        default=None, alias="schema", description="Optional schema snapshot override"
    )
    dialect: str | None = Field(default=None, description="Target SQL dialect override")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class JoinPathRequest(BaseModel):
    """Request model for /join-path endpoint."""

    active_tables: list[str] = Field(
        description="List of active tables currently joined"
    )
    target_table: str = Field(description="Target table to connect to the active graph")
    schema_snapshot: dict[str, Any] | None = Field(
        default=None, alias="schema", description="Optional schema snapshot override"
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class NlqRequest(BaseModel):
    """Request model for /nlq endpoint."""

    prompt: str = Field(description="Natural language query prompt")
    schema_snapshot: dict[str, Any] | None = Field(
        default=None, alias="schema", description="Optional schema snapshot override"
    )
    dialect: str | None = Field(default=None, description="Target SQL dialect override")
    provider: str | None = Field(default=None, description="NLQ provider override")
    current_spec: dict[str, Any] | None = Field(
        default=None,
        description="Optional active QuerySpec on canvas for multi-turn refinement",
    )
    history: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional prior conversation turns for multi-shot refinement",
    )
    options: dict[str, Any] = Field(
        default_factory=dict, description="Additional translation options"
    )

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ExportRequest(BaseModel):
    """Request model for /export endpoint."""

    format: str = Field(
        default="csv",
        description="Target export format: csv, json, parquet, excel, xlsx, jsonl, ndjson, arrow",
    )
    spec: dict[str, Any] | None = Field(
        default=None, description="Declarative QuerySpec to execute and export"
    )
    rows: list[Any] | None = Field(
        default=None, description="Pre-computed rows to serialize directly"
    )
    columns: list[str] | None = Field(
        default=None, description="Column names corresponding to rows"
    )
    sql: str | None = Field(default=None, description="Raw SQL to execute and export")
    params: list[Any] | None = Field(
        default=None, description="Parameters for raw SQL execution"
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream response in chunks using StreamingResponse",
    )

    model_config = ConfigDict(extra="allow")


async def _resolve_conn(connector: Any) -> Any:
    """Resolves connector from instance, factory callable, or registry name."""
    if isinstance(connector, str):
        return get_connector(connector)
    if (
        callable(connector)
        and not hasattr(connector, "execute")
        and not isinstance(connector, BaseConnector)
    ):
        res = connector()
        if inspect.isawaitable(res):
            return await res
        return res
    return connector


async def _exec_conn_method(
    conn: Any, method_name: str, *args: Any, **kwargs: Any
) -> Any:
    """Executes a connector method supporting both synchronous and asynchronous connectors."""
    method = getattr(conn, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    res = method(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res


def _is_tenant_isolation_active(
    policy: Any,
    tenant_ctx: Any,
    payload: Any,
) -> bool:
    """Returns True if tenant isolation is enforced via policy, resolved context, or request payload."""
    if policy and getattr(policy, "enforce_tenant_isolation", False):
        return True
    if tenant_ctx is not None:
        return True
    tenant_id = getattr(payload, "tenant_id", None)
    if not tenant_id and hasattr(payload, "model_extra") and payload.model_extra:
        tenant_id = payload.model_extra.get("tenant_id")
    if not tenant_id and isinstance(payload, dict):
        tenant_id = payload.get("tenant_id")
    if tenant_id:
        return True
    ctx = getattr(payload, "context", None)
    if not ctx and hasattr(payload, "model_extra") and payload.model_extra:
        ctx = payload.model_extra.get("context")
    if not ctx and isinstance(payload, dict):
        ctx = payload.get("context")
    if isinstance(ctx, dict) and ctx.get("tenant_id"):
        return True
    if getattr(ctx, "tenant_id", None):
        return True
    pol = getattr(payload, "policy", None)
    if not pol and hasattr(payload, "model_extra") and payload.model_extra:
        pol = payload.model_extra.get("policy")
    if not pol and isinstance(payload, dict):
        pol = payload.get("policy")
    if isinstance(pol, dict) and pol.get("enforce_tenant_isolation"):
        return True
    if getattr(pol, "enforce_tenant_isolation", False):
        return True
    return False


def create_query_builder_router(
    connector: Any,
    security: SecurityPolicy | SecurityConfig | dict[str, Any] | None = None,
    tenant_resolver: Callable[
        [Request],
        TenantContext | Awaitable[TenantContext] | dict[str, Any] | str | None,
    ]
    | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    prefix: str = "",
    tags: list[str] | None = None,
    schema_cache_ttl: float = 0.0,
    nlq_service: Any = None,
    ai_provider: Any = None,
) -> APIRouter:
    """Creates a turnkey FastAPI APIRouter for Query-Builder.

    Parameters
    ----------
    connector:
        Database connector instance (BaseConnector), factory callable, or connector name string.
    security:
        Security policy configuration (SecurityPolicy, SecurityConfig, or dict). If None and a tenant_resolver
        is configured, defaults to fail-closed tenant isolation.
    tenant_resolver:
        Callable taking a FastAPI Request and returning a TenantContext (or string tenant_id).
        Can be sync or async. Fails closed (401 Unauthorized) if resolution returns None,
        empty tenant_id, or raises an error.
    capabilities:
        Engine capabilities or dictionary defining enabled/advanced/disabled features.
    prefix:
        URL path prefix for all registered routes (e.g. "/api/query-builder").
    tags:
        OpenAPI documentation tags (defaults to ["Query Builder"]).
    schema_cache_ttl:
        Time-to-live in seconds for cached schema introspection. Defaults to 0.0 (disabled).
    nlq_service:
        Optional NlqService instance for /nlq natural language translation.
    ai_provider:
        Optional AI provider instance or callable for /nlq endpoint.

    Returns
    -------
    fastapi.APIRouter
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is not installed. Install via 'pip install fastapi pydantic' to use create_query_builder_router."
        )

    router = APIRouter(prefix=prefix, tags=tags or ["Query Builder"])

    import time

    cached_schema_data: dict[str, Any] | None = None
    cached_schema_time: float = 0.0

    effective_capabilities: EngineCapabilities = (
        capabilities
        if isinstance(capabilities, EngineCapabilities)
        else (
            EngineCapabilities.from_dict(capabilities)
            if isinstance(capabilities, dict)
            else EngineCapabilities.default()
        )
    )

    async def get_tenant_context(request: Request) -> TenantContext | None:
        """Securely resolves tenant context from request, failing closed."""
        if tenant_resolver is None:
            return None

        try:
            res = tenant_resolver(request)
            if inspect.isawaitable(res):
                res = await res

            if res is None:
                raise HTTPException(
                    status_code=401,
                    detail="Unauthorized: TenantContext could not be resolved from request.",
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
                raise HTTPException(
                    status_code=401,
                    detail=f"Unauthorized: Invalid tenant context type '{type(res).__name__}'.",
                )

            if not ctx.tenant_id or not str(ctx.tenant_id).strip():
                raise HTTPException(
                    status_code=401,
                    detail="Unauthorized: Resolved TenantContext contains empty or missing tenant_id.",
                )

            return ctx
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail=public_error("Unauthorized: Tenant authentication failed", exc),
            ) from exc

    def get_effective_policy() -> SecurityPolicy | None:
        """Determines the active SecurityPolicy based on security and tenant_resolver configuration."""
        if security is None:
            if tenant_resolver is not None:
                return SecurityPolicy(enforce_tenant_isolation=True)
            return None
        if isinstance(security, SecurityPolicy):
            if tenant_resolver is not None:
                security.enforce_tenant_isolation = True
            return security
        if isinstance(security, dict):
            pol = SecurityPolicy(**security)
            if tenant_resolver is not None:
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
                if tenant_resolver is not None
                else getattr(security.privacy, "enforce_tenant_isolation", False),
                sensitive_column_patterns=getattr(
                    security.privacy, "sensitive_column_patterns", []
                ),
                masking_strategy=getattr(
                    security.privacy, "masking_strategy", "redact"
                ),
                max_complexity_score=getattr(
                    security.execution, "max_complexity_score", None
                )
                if hasattr(security, "execution")
                else None,
            )
            return pol
        # Duck-typed policy object (neither SecurityConfig nor dict): passed through as-is.
        return cast("SecurityPolicy | None", security)

    @router.get("/capabilities", summary="Get Engine Capabilities")
    async def get_capabilities() -> dict[str, Any]:
        """Returns the active engine capabilities and feature tiers."""
        return {"capabilities": effective_capabilities.to_dict()}

    @router.get("/schema", summary="Introspect Database Schema")
    @router.get(
        "/introspect",
        summary="Introspect Database Schema (Alias)",
        include_in_schema=False,
    )
    async def get_schema(refresh: bool = False) -> dict[str, Any]:
        """Introspects tables, columns, and foreign keys from the configured connector."""
        nonlocal cached_schema_data, cached_schema_time
        if (
            not refresh
            and schema_cache_ttl > 0.0
            and cached_schema_data is not None
            and (time.monotonic() - cached_schema_time) < schema_cache_ttl
        ):
            return cached_schema_data

        conn = await _resolve_conn(connector)
        try:
            snapshot = await _exec_conn_method(conn, "introspect_schema")
            if hasattr(snapshot, "to_dict"):
                data = snapshot.to_dict()
            elif is_dataclass(snapshot) and not isinstance(snapshot, type):
                data = asdict(snapshot)
            elif isinstance(snapshot, dict):
                data = dict(snapshot)
            else:
                try:
                    data = dict(snapshot)
                except (TypeError, ValueError):
                    data = {"tables": {}}

            data["capabilities"] = effective_capabilities.to_dict()

            policy = get_effective_policy()
            if policy and "tables" in data and isinstance(data["tables"], dict):
                allowed = (
                    set(policy.allowed_tables)
                    if policy.allowed_tables is not None
                    else None
                )
                restricted = set(policy.restricted_tables or [])
                data["tables"] = {
                    tname: tmeta
                    for tname, tmeta in data["tables"].items()
                    if (allowed is None or tname in allowed) and tname not in restricted
                }
            if schema_cache_ttl > 0.0:
                cached_schema_data = dict(data)
                cached_schema_time = time.monotonic()
            return data
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=public_error("Schema introspection failed", exc)
            ) from exc

    @router.post("/compile", summary="Compile Query Specification to SQL")
    async def compile_query(
        payload: CompileRequest, request: Request
    ) -> dict[str, Any]:
        """Compiles declarative QuerySpec into dialect-specific SQL with security policies applied."""
        if (
            not payload.spec
            or not isinstance(payload.spec, dict)
            or not payload.spec.get("table")
        ):
            raise HTTPException(
                status_code=400,
                detail="Missing required 'table' in query specification 'spec'.",
            )

        conn = await _resolve_conn(connector)
        tenant_ctx = await get_tenant_context(request)
        policy = get_effective_policy()

        try:
            active_spec = payload.spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    payload.spec,
                    schema=payload.schema_snapshot,
                    context=tenant_ctx,
                    policy=policy,
                )

            dialect = payload.dialect or getattr(conn, "dialect_name", "postgres")
            compiler = QueryCompiler(
                active_spec,
                schema=payload.schema_snapshot,
                dialect=dialect,
                capabilities=effective_capabilities,
            )
            main_sql, params, count_sql, count_params = compiler.compile()
            val_res = validate_sql_ast(main_sql, dialect=dialect)
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Security violation: {'; '.join(violations)}",
                )
            return {
                "sql": main_sql,
                "params": params,
                "count_sql": count_sql,
                "count_params": count_params,
                "dialect": dialect,
            }
        except HTTPException:
            raise
        except DisabledFeatureError as exc:
            raise HTTPException(
                status_code=403,
                detail=disabled_feature_message(exc, effective_capabilities),
            ) from exc
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (CompilationError, Exception) as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Compilation error", exc)
            ) from exc

    @router.post("/validate", summary="Validate SQL AST Safety")
    async def validate_query(payload: ValidateRequest) -> dict[str, Any]:
        """Validates arbitrary SQL AST safety, mutation restrictions, and table allowlists."""
        try:
            result = validate_sql_ast(
                payload.sql, allowed_schemas=payload.allowed_schemas
            )
            return result
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Validation error", exc)
            ) from exc

    @router.post("/execute", summary="Execute Query Specification or SQL")
    async def execute_query(
        payload: ExecuteRequest, request: Request
    ) -> dict[str, Any]:
        """Executes a declarative QuerySpec or SQL query against the database connector."""
        conn = await _resolve_conn(connector)
        tenant_ctx = await get_tenant_context(request)
        policy = get_effective_policy()

        target_spec = payload.spec or payload.query

        if target_spec is None and not payload.sql:
            raise HTTPException(
                status_code=400,
                detail="Either 'spec', 'query', or 'sql' must be provided in request body.",
            )

        if target_spec is not None and (
            not isinstance(target_spec, dict) or not target_spec.get("table")
        ):
            raise HTTPException(
                status_code=400,
                detail="Missing required 'table' in query specification.",
            )

        try:
            if target_spec is not None:
                # Apply fail-closed security and RLS policy
                if policy is not None or tenant_ctx is not None:
                    active_spec = apply_security_policy(
                        target_spec,
                        context=tenant_ctx,
                        policy=policy,
                    )
                else:
                    active_spec = target_spec

                if target_spec.get("ctes"):
                    effective_capabilities.require_feature("ctes")
                if target_spec.get("window_functions"):
                    effective_capabilities.require_feature("window_functions")
                if (
                    target_spec.get("rollup")
                    or target_spec.get("cube")
                    or target_spec.get("grouping_sets")
                    or target_spec.get("pivot")
                ):
                    effective_capabilities.require_feature("analytical_grouping")
                if target_spec.get("vector_search") or target_spec.get("hybrid_search"):
                    effective_capabilities.require_feature("vector_search")

                exec_kwargs: dict[str, Any] = {}
                if payload.timeout_ms is not None:
                    exec_kwargs["statement_timeout_ms"] = int(payload.timeout_ms)

                result = await _exec_conn_method(
                    conn, "execute", active_spec, **exec_kwargs
                )
                if hasattr(result, "to_dict"):
                    return result.to_dict()
                if isinstance(result, dict):
                    return result

                # In case connector returns a QueryResult dataclass
                return {
                    "columns": getattr(result, "columns", []),
                    "rows": getattr(result, "rows", []),
                    "count": len(getattr(result, "rows", [])),
                    "latency_ms": getattr(result, "latency_ms", 0.0),
                    "dialect": getattr(conn, "dialect_name", "sqlite"),
                    "sql": getattr(result, "sql", ""),
                }

            # Raw SQL execution path
            if not effective_capabilities.is_enabled("raw_sql"):
                raise HTTPException(
                    status_code=403,
                    detail="Feature 'raw_sql' is disabled in active engine capabilities.",
                )

            # Strictly restrict raw SQL if tenant isolation is enforced
            if _is_tenant_isolation_active(policy, tenant_ctx, payload):
                raise HTTPException(
                    status_code=403,
                    detail="Raw SQL execution is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
                )

            # Guarded above: with no spec, ``payload.sql`` is a non-empty string.
            val_res = validate_sql_ast(cast("str", payload.sql))
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Security violation: {'; '.join(violations)}",
                )

            cols, rows, latency = await _exec_conn_method(
                conn, "execute_raw", payload.sql, payload.params or []
            )
            return {
                "columns": cols,
                "rows": rows,
                "count": len(rows),
                "limit": payload.limit or len(rows),
                "offset": payload.offset or 0,
                "latency_ms": round(latency, 2),
                "dialect": getattr(conn, "dialect_name", "sqlite"),
                "sql": payload.sql,
            }
        except HTTPException:
            raise
        except DisabledFeatureError as exc:
            raise HTTPException(
                status_code=403,
                detail=disabled_feature_message(exc, effective_capabilities),
            ) from exc
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Query execution error", exc)
            ) from exc

    async def _resolve_export_data(payload: ExportRequest, request: Request) -> Any:
        conn = await _resolve_conn(connector)
        tenant_ctx = await get_tenant_context(request)
        policy = get_effective_policy()

        if payload.rows is not None:
            return {
                "rows": payload.rows,
                "columns": payload.columns or [],
            }
        elif payload.spec is not None:
            if not isinstance(payload.spec, dict) or not payload.spec.get("table"):
                raise HTTPException(
                    status_code=400,
                    detail="Missing required 'table' in query specification.",
                )
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    payload.spec,
                    context=tenant_ctx,
                    policy=policy,
                )
            else:
                active_spec = payload.spec

            res = await _exec_conn_method(conn, "execute", active_spec)
            if isinstance(res, dict):
                return {
                    "rows": res.get("rows", []),
                    "columns": res.get("columns", []),
                }
            else:
                return {
                    "rows": getattr(res, "rows", []),
                    "columns": getattr(res, "columns", []),
                }
        elif payload.sql is not None:
            if not effective_capabilities.is_enabled("raw_sql"):
                raise HTTPException(
                    status_code=403,
                    detail="Feature 'raw_sql' is disabled in active engine capabilities.",
                )
            if _is_tenant_isolation_active(policy, tenant_ctx, payload):
                raise HTTPException(
                    status_code=403,
                    detail="Raw SQL export is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
                )
            val_res = validate_sql_ast(payload.sql)
            if not val_res.get("valid") or not val_res.get("is_read_only"):
                violations = val_res.get(
                    "violations", ["Query failed AST safety validation."]
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Security violation: {'; '.join(violations)}",
                )
            cols, rows, _ = await _exec_conn_method(
                conn, "execute_raw", payload.sql, payload.params or []
            )
            return {"rows": rows, "columns": cols}
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'rows', 'spec', or 'sql' must be provided for export.",
            )

    @router.post("/export", summary="Export Dataset in Multiple Formats")
    async def export_query(payload: ExportRequest, request: Request) -> Response:
        """Executes query and streams/downloads serialized tabular dataset (CSV, JSON, Parquet, Excel, Arrow)."""
        try:
            export_data = await _resolve_export_data(payload, request)

            if payload.stream:
                stream_iter, mime_type, ext = stream_export_dataset(
                    export_data, format=payload.format
                )
                return StreamingResponse(
                    stream_iter,
                    media_type=mime_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="export.{ext}"'
                    },
                )

            content_bytes, mime_type, ext = export_dataset(
                export_data, format=payload.format
            )

            return Response(
                content=content_bytes,
                media_type=mime_type,
                headers={"Content-Disposition": f'attachment; filename="export.{ext}"'},
            )
        except HTTPException:
            raise
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ExportError, Exception) as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Export error", exc)
            ) from exc

    @router.post("/export/stream", summary="Stream Dataset Export in Chunks")
    async def stream_export_query(payload: ExportRequest, request: Request) -> Response:
        """Executes query and streams chunked dataset (CSV, JSON, Parquet, Excel, Arrow) using StreamingResponse."""
        try:
            export_data = await _resolve_export_data(payload, request)
            stream_iter, mime_type, ext = stream_export_dataset(
                export_data, format=payload.format
            )
            return StreamingResponse(
                stream_iter,
                media_type=mime_type,
                headers={"Content-Disposition": f'attachment; filename="export.{ext}"'},
            )
        except HTTPException:
            raise
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ExportError, Exception) as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Streaming export error", exc)
            ) from exc

    @router.post("/explain", summary="Explain Query Execution Plan and Performance")
    async def explain_query(
        payload: ExplainRequest, request: Request
    ) -> dict[str, Any]:
        """Analyzes query execution plan, index suggestions, and potential Cartesian bottlenecks."""
        target_spec = payload.spec or payload.query
        if (
            not target_spec
            or not isinstance(target_spec, dict)
            or not target_spec.get("table")
        ):
            raise HTTPException(
                status_code=400,
                detail="Missing required 'table' in query specification.",
            )
        conn = await _resolve_conn(connector)
        tenant_ctx = await get_tenant_context(request)
        policy = get_effective_policy()

        try:
            active_spec = target_spec
            if policy is not None or tenant_ctx is not None:
                active_spec = apply_security_policy(
                    target_spec,
                    schema=payload.schema_snapshot,
                    context=tenant_ctx,
                    policy=policy,
                )

            dialect = payload.dialect or getattr(conn, "dialect_name", "postgres")
            compiler = QueryCompiler(
                active_spec,
                schema=payload.schema_snapshot,
                dialect=dialect,
                capabilities=effective_capabilities,
            )
            sql, params = compiler.compile()[0:2]
            plan = estimate_plan_from_spec(active_spec, schema=payload.schema_snapshot)
            perf = analyze_query_performance(
                active_spec, sql=sql, dialect=str(dialect or "postgres")
            )
            rec_indexes = recommend_indexes(active_spec)
            return {
                "sql": sql,
                "params": params,
                "dialect": dialect,
                "plan": plan,
                "performance": perf,
                "recommended_indexes": rec_indexes,
            }
        except HTTPException:
            raise
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Explain failed", exc)
            ) from exc

    @router.post("/join-path", summary="Find Relational Join Path")
    async def get_join_path(payload: JoinPathRequest) -> dict[str, Any]:
        """Finds shortest relational join path from active tables to target table."""
        try:
            conn = await _resolve_conn(connector)
            schema_data = payload.schema_snapshot
            if schema_data is None:
                raw_schema = await _exec_conn_method(conn, "introspect_schema")
                schema_data = (
                    raw_schema.to_dict()
                    if hasattr(raw_schema, "to_dict")
                    else (
                        asdict(raw_schema)
                        if is_dataclass(raw_schema) and not isinstance(raw_schema, type)
                        else dict(raw_schema)
                    )
                )

            policy = get_effective_policy()
            if (
                policy
                and "tables" in schema_data
                and isinstance(schema_data["tables"], dict)
            ):
                allowed = (
                    set(policy.allowed_tables)
                    if policy.allowed_tables is not None
                    else None
                )
                restricted = set(policy.restricted_tables or [])
                schema_data["tables"] = {
                    tname: tmeta
                    for tname, tmeta in schema_data["tables"].items()
                    if (allowed is None or tname in allowed) and tname not in restricted
                }

            path_steps = find_join_path(
                payload.active_tables,
                payload.target_table,
                schema_data=schema_data,
            )
            return {
                "path": path_steps,
                "connected": bool(path_steps),
                "target_table": payload.target_table,
            }
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Join path solver failed", exc)
            ) from exc

    @router.post("/nlq", summary="Translate Natural Language to Query")
    @router.post("/nlq/translate", include_in_schema=False)
    @router.post("/v1/nlq/translate", include_in_schema=False)
    async def translate_nlq(payload: NlqRequest, request: Request) -> dict[str, Any]:
        """Translates natural language query into verified QuerySpec and dialect SQL with tenant policy applied."""
        if not payload.prompt or not payload.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt must not be empty.")

        conn = await _resolve_conn(connector)
        tenant_ctx = await get_tenant_context(request)
        policy = get_effective_policy()

        try:
            schema_data = payload.schema_snapshot
            if schema_data is None:
                raw_schema = await _exec_conn_method(conn, "introspect_schema")
                schema_data = (
                    raw_schema.to_dict()
                    if hasattr(raw_schema, "to_dict")
                    else (
                        asdict(raw_schema)
                        if is_dataclass(raw_schema) and not isinstance(raw_schema, type)
                        else dict(raw_schema)
                    )
                )

            if (
                policy
                and "tables" in schema_data
                and isinstance(schema_data["tables"], dict)
            ):
                allowed = (
                    set(policy.allowed_tables)
                    if policy.allowed_tables is not None
                    else None
                )
                restricted = set(policy.restricted_tables or [])
                schema_data["tables"] = {
                    tname: tmeta
                    for tname, tmeta in schema_data["tables"].items()
                    if (allowed is None or tname in allowed) and tname not in restricted
                }

            dialect_str = str(
                payload.dialect
                or getattr(conn, "dialect_name", "postgres")
                or "postgres"
            )
            used_provider = payload.provider or getattr(
                nlq_service, "default_provider", "mock"
            )
            used_model = ""
            follow_ups_list: list[str] = []
            if (
                nlq_service is not None
                and ai_provider is None
                and hasattr(nlq_service, "translate")
            ):
                nlq_res = nlq_service.translate(
                    {
                        "prompt": payload.prompt,
                        "schema": schema_data,
                        "dialect": dialect_str,
                        "provider": payload.provider,
                        "current_spec": payload.current_spec,
                        "history": payload.history,
                        "options": payload.options,
                    }
                )
                res_dict = (
                    nlq_res.to_dict() if hasattr(nlq_res, "to_dict") else dict(nlq_res)
                )
                raw_spec = dict(res_dict.get("spec") or res_dict.get("query") or {})
                explanation = res_dict.get("explanation") or ""
                confidence = res_dict.get("confidence", 1.0)
                warnings_list = res_dict.get("warnings", [])
                follow_ups_list = list(res_dict.get("follow_ups") or [])
                used_provider = str(res_dict.get("provider") or used_provider)
                used_model = str(res_dict.get("model") or "")
            else:
                from query_builder.ai.client import ask_ai

                ai_res = ask_ai(
                    prompt=payload.prompt,
                    ai=ai_provider,
                    schema=schema_data,
                    dialect=dialect_str,
                    options=payload.options,
                )
                raw_spec = dict(ai_res.spec)
                explanation = ai_res.explanation
                confidence = ai_res.confidence
                warnings_list = ai_res.warnings

            if policy is not None or tenant_ctx is not None:
                raw_spec = apply_security_policy(
                    raw_spec,
                    schema=schema_data,
                    context=tenant_ctx,
                    policy=policy,
                )

            tables_dict = (
                schema_data.get("tables")
                if isinstance(schema_data, dict)
                and isinstance(schema_data.get("tables"), dict)
                else None
            )
            if tables_dict:
                base_tbl = str(raw_spec.get("table") or "")
                clean_base_tbl = base_tbl.split(".")[-1]
                if base_tbl not in tables_dict and clean_base_tbl not in tables_dict:
                    fallback_tbl = next(
                        (
                            t
                            for t in tables_dict
                            if not t.startswith(
                                ("django_", "auth_permission", "sqlite_")
                            )
                        ),
                        next(iter(tables_dict)),
                    )
                    warnings_list = list(warnings_list) + [
                        f"Mapped ungrounded table '{base_tbl}' to '{fallback_tbl}'."
                    ]
                    raw_spec["table"] = fallback_tbl
                    raw_spec["columns"] = []
                    raw_spec["joins"] = []
                    raw_spec["filters"] = []
                    raw_spec["having"] = []
                    raw_spec["order_by"] = []
                else:
                    if isinstance(raw_spec.get("joins"), list):
                        raw_spec["joins"] = [
                            j
                            for j in raw_spec["joins"]
                            if isinstance(j, dict)
                            and (
                                j.get("table") in tables_dict
                                or str(j.get("table") or "").split(".")[-1]
                                in tables_dict
                            )
                        ]
                    active_tbl_names = [
                        base_tbl if base_tbl in tables_dict else clean_base_tbl,
                        *(
                            j.get("table")
                            if j.get("table") in tables_dict
                            else str(j.get("table") or "").split(".")[-1]
                            for j in (raw_spec.get("joins") or [])
                            if isinstance(j, dict)
                        ),
                    ]
                    valid_cols_map: dict[str, str] = {}
                    for t_name in active_tbl_names:
                        t_meta = tables_dict.get(t_name)
                        if isinstance(t_meta, dict):
                            raw_c = t_meta.get("columns", {})
                            if isinstance(raw_c, dict):
                                for cn in raw_c:
                                    valid_cols_map[str(cn).lower()] = str(cn)
                            elif isinstance(raw_c, list):
                                for c_item in raw_c:
                                    cn = (
                                        c_item.get("name")
                                        if isinstance(c_item, dict)
                                        else str(c_item)
                                    )
                                    if cn:
                                        valid_cols_map[str(cn).lower()] = str(cn)
                    if valid_cols_map:
                        first_valid_col = next(iter(valid_cols_map.values()))
                        col_aliases: set[str] = set()
                        cleaned_cols: list[Any] = []
                        for col_entry in raw_spec.get("columns") or []:
                            if isinstance(col_entry, str):
                                bare_c = col_entry.split(".")[-1].strip()
                                if bare_c == "*" or bare_c.lower() in valid_cols_map:
                                    cleaned_cols.append(col_entry)
                            elif isinstance(col_entry, dict):
                                if col_entry.get("alias"):
                                    col_aliases.add(str(col_entry["alias"]).lower())
                                c_ref = str(col_entry.get("column") or "").strip()
                                bare_c = c_ref.split(".")[-1]
                                if (
                                    not c_ref
                                    or bare_c == "*"
                                    or bare_c.lower() in valid_cols_map
                                ):
                                    cleaned_cols.append(col_entry)
                                elif col_entry.get("agg"):
                                    patched_col = dict(col_entry)
                                    patched_col["column"] = first_valid_col
                                    cleaned_cols.append(patched_col)
                        raw_spec["columns"] = cleaned_cols
                        if isinstance(raw_spec.get("filters"), list):
                            raw_spec["filters"] = [
                                f
                                for f in raw_spec["filters"]
                                if isinstance(f, dict)
                                and str(f.get("column") or "").split(".")[-1].lower()
                                in valid_cols_map
                            ]
                        if isinstance(raw_spec.get("having"), list):
                            raw_spec["having"] = [
                                h
                                for h in raw_spec["having"]
                                if isinstance(h, dict)
                                and (
                                    str(h.get("column") or "").split(".")[-1] == "*"
                                    or str(h.get("column") or "").split(".")[-1].lower()
                                    in valid_cols_map
                                    or str(h.get("column") or "").lower() in col_aliases
                                )
                            ]
                        if isinstance(raw_spec.get("order_by"), list):
                            raw_spec["order_by"] = [
                                o
                                for o in raw_spec["order_by"]
                                if isinstance(o, dict)
                                and (
                                    str(o.get("column") or "").split(".")[-1].lower()
                                    in valid_cols_map
                                    or str(o.get("column") or "").lower() in col_aliases
                                )
                            ]

            compiler = QueryCompiler(
                raw_spec,
                schema=schema_data,
                dialect=dialect_str,
                capabilities=effective_capabilities,
            )
            final_sql, final_params = compiler.compile()[0:2]
            if not follow_ups_list:
                tbl_for_sug = str(raw_spec.get("table") or "records")
                cur_limit = raw_spec.get("limit", 50)
                next_limit = 10 if cur_limit != 10 else 25
                follow_ups_list = [
                    f"Limit results to {next_limit} rows",
                    f"Count {tbl_for_sug} rows",
                    "Only show distinct rows",
                ]
            return {
                "spec": raw_spec,
                "sql": final_sql,
                "params": final_params,
                "explanation": explanation,
                "confidence": confidence,
                "warnings": warnings_list,
                "follow_ups": follow_ups_list,
                "provider": used_provider,
                "model": used_model,
            }
        except HTTPException:
            raise
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("NLQ translation failed", exc)
            ) from exc

    @router.post("/nlq/explain", summary="Explain Query in Natural Language")
    @router.post("/v1/nlq/explain", include_in_schema=False)
    async def explain_nlq(payload: ExplainRequest, request: Request) -> dict[str, Any]:
        """Explains a visual QuerySpec in plain English."""
        target_spec = payload.spec or payload.query
        if not target_spec or not isinstance(target_spec, dict):
            raise HTTPException(
                status_code=400,
                detail="Missing required 'query' or 'spec' dictionary.",
            )
        conn = await _resolve_conn(connector)
        dialect_str = str(
            payload.dialect or getattr(conn, "dialect_name", "postgres") or "postgres"
        )
        req_provider = (
            getattr(payload, "model_extra", {}).get("provider")
            if hasattr(payload, "model_extra") and payload.model_extra
            else None
        )
        from query_builder.nlq.service import NlqService

        svc = (
            nlq_service
            if (nlq_service is not None and hasattr(nlq_service, "explain"))
            else NlqService()
        )
        provider_name = str(req_provider or getattr(svc, "default_provider", "mock"))
        try:
            exp_res = svc.explain(
                target_spec,
                dialect=dialect_str,
                provider=provider_name,
            )
            if hasattr(exp_res, "to_dict"):
                return dict(exp_res.to_dict())
            if isinstance(exp_res, dict):
                return dict(exp_res)
            return {}
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("NLQ explain failed", exc)
            ) from exc

    @router.get("/nlq/providers", summary="List Available NLQ Providers")
    @router.get("/v1/nlq/providers", include_in_schema=False)
    async def get_nlq_providers() -> dict[str, Any]:
        """Lists registered NLQ LLM providers and their runtime configuration status."""
        from query_builder.nlq.service import NlqService

        svc = (
            nlq_service
            if (
                nlq_service is not None
                and hasattr(nlq_service, "list_available_providers")
            )
            else NlqService()
        )
        return {
            "providers": svc.list_available_providers(),
            "default_provider": getattr(svc, "default_provider", "mock"),
        }

    return router
