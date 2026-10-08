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
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request, Response
    from pydantic import BaseModel, ConfigDict, Field

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    APIRouter = object  # type: ignore[misc, assignment]
    HTTPException = Exception  # type: ignore[misc, assignment]
    Request = Any  # type: ignore[misc, assignment]
    Response = Any  # type: ignore[misc, assignment]
    BaseModel = object  # type: ignore[misc, assignment]
    ConfigDict = dict  # type: ignore[misc, assignment]

    def Field(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc, assignment]
        return None


from query_builder.ast_validator import validate_sql_ast
from query_builder.capabilities import (
    DisabledFeatureError,
    EngineCapabilities,
)
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.config import SecurityConfig
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.registry import get_connector
from query_builder.export import ExportError, export_dataset
from query_builder.integrations._errors import public_error
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

    Returns
    -------
    fastapi.APIRouter
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is not installed. Install via 'pip install fastapi pydantic' to use create_query_builder_router."
        )

    router = APIRouter(prefix=prefix, tags=tags or ["Query Builder"])

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
        return security

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
    async def get_schema() -> dict[str, Any]:
        """Introspects tables, columns, and foreign keys from the configured connector."""
        conn = await _resolve_conn(connector)
        try:
            snapshot = await _exec_conn_method(conn, "introspect_schema")
            if is_dataclass(snapshot) and not isinstance(snapshot, type):
                data = asdict(snapshot)
            elif hasattr(snapshot, "to_dict"):
                data = snapshot.to_dict()
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
            return {
                "sql": main_sql,
                "params": params,
                "count_sql": count_sql,
                "count_params": count_params,
                "dialect": dialect,
            }
        except HTTPException:
            raise
        except (SecurityError, DisabledFeatureError) as exc:
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
            if policy and getattr(policy, "enforce_tenant_isolation", False):
                raise HTTPException(
                    status_code=403,
                    detail="Raw SQL execution is restricted when tenant isolation is enforced. Please use structured QuerySpec.",
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
        except (SecurityError, DisabledFeatureError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=public_error("Query execution error", exc)
            ) from exc

    @router.post("/export", summary="Export Dataset in Multiple Formats")
    async def export_query(payload: ExportRequest, request: Request) -> Response:
        """Executes query and streams/downloads serialized tabular dataset (CSV, JSON, Parquet, Excel, Arrow)."""
        conn = await _resolve_conn(connector)
        tenant_ctx = await get_tenant_context(request)
        policy = get_effective_policy()

        try:
            if payload.rows is not None:
                export_data: Any = {
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
                    export_data = {
                        "rows": res.get("rows", []),
                        "columns": res.get("columns", []),
                    }
                else:
                    export_data = {
                        "rows": getattr(res, "rows", []),
                        "columns": getattr(res, "columns", []),
                    }
            elif payload.sql is not None:
                if policy and getattr(policy, "enforce_tenant_isolation", False):
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
                export_data = {"rows": rows, "columns": cols}
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Either 'rows', 'spec', or 'sql' must be provided for export.",
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

    return router
