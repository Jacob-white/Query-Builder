"""
SQLAlchemy Engine & Session Integration for Query-Builder.
==========================================================
Provides first-class integration with SQLAlchemy 2.0+ Engines, Connections,
Sessions, and Declarative MetaData:
- Live schema introspection via `sqlalchemy.inspect` or `MetaData` reflection
- Declarative `QuerySpec` compilation into `sqlalchemy.text()` with named bind parameters
- Policy-enforced read-only query execution with `SecurityPolicy`, `TenantContext`,
  and `EngineCapabilities` governance
"""

from __future__ import annotations

import importlib
import re
import time
from dataclasses import asdict, is_dataclass, replace
from typing import Any

from query_builder.adapters.sqlalchemy import _reflect_live_sqlalchemy
from query_builder.ast_validator import validate_sql_ast
from query_builder.capabilities import EngineCapabilities
from query_builder.compiler import QueryCompiler
from query_builder.models import QuerySpec
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.security import SecurityError

_DIALECT_MAP: dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "psycopg": "postgres",
    "psycopg2": "postgres",
    "asyncpg": "postgres",
    "sqlite": "sqlite",
    "pysqlite": "sqlite",
    "aiosqlite": "sqlite",
    "mysql": "mysql",
    "mariadb": "mysql",
    "pymysql": "mysql",
    "mssql": "mssql",
    "pyodbc": "mssql",
    "pymssql": "mssql",
    "oracle": "oracle",
    "oracledb": "oracle",
    "duckdb": "duckdb",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
}

_PARAM_PLACEHOLDER_RE = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\$(\d+)|\?|%s")


def _get_sqlalchemy() -> Any:
    """Lazily imports SQLAlchemy or raises an informative ImportError."""
    try:
        sa = importlib.import_module("sqlalchemy")
        if sa is None:
            raise ImportError("SQLAlchemy is not installed")
        return sa
    except ImportError as exc:
        raise ImportError(
            "SQLAlchemy is not installed. Install via 'pip install sqlalchemy>=2.0.0' "
            "or 'pip install query-builder-engine[sqlalchemy]'."
        ) from exc


def _normalize_tenant_context(
    context: TenantContext | dict[str, Any] | str | None,
) -> TenantContext | None:
    """Normalizes a tenant context input into a TenantContext instance."""
    if context is None:
        return None
    if isinstance(context, TenantContext):
        if not context.tenant_id or not str(context.tenant_id).strip():
            raise PermissionError(
                "Unauthorized: TenantContext contains empty tenant_id."
            )
        return context
    if isinstance(context, str):
        clean_id = context.strip()
        if not clean_id:
            raise PermissionError(
                "Unauthorized: TenantContext contains empty tenant_id."
            )
        return TenantContext(tenant_id=clean_id)
    if isinstance(context, dict):
        t_id = str(context.get("tenant_id", "")).strip()
        if not t_id:
            raise PermissionError(
                "Unauthorized: TenantContext dictionary is missing 'tenant_id'."
            )
        known = {"tenant_id", "user_id", "roles", "attributes"}
        extra = {k: v for k, v in context.items() if k not in known}
        attrs = dict(context.get("attributes") or {})
        attrs.update(extra)
        return TenantContext(
            tenant_id=t_id,
            user_id=context.get("user_id"),
            roles=list(context.get("roles") or []),
            attributes=attrs,
        )
    raise PermissionError(
        f"Unauthorized: Invalid tenant context type {type(context).__name__}."
    )


def _to_named_parameters(sql: str, params: list[Any]) -> tuple[str, dict[str, Any]]:
    """Converts positional placeholders ($1, ?, %s) into :p0, :p1 named binds while skipping quoted literals."""
    if not params:
        return sql, {}

    bind_dict: dict[str, Any] = {f"p{i}": val for i, val in enumerate(params)}
    pos_counter = 0

    def _replace_match(match: re.Match[str]) -> str:
        nonlocal pos_counter
        token = match.group(0)
        if token.startswith("'") or token.startswith('"'):
            return token
        pg_idx = match.group(1)
        if pg_idx is not None:
            idx = int(pg_idx) - 1
            return f":p{idx}"
        idx = pos_counter
        pos_counter += 1
        return f":p{idx}"

    named_sql = _PARAM_PLACEHOLDER_RE.sub(_replace_match, sql)
    return named_sql, bind_dict


def _coerce_policy(
    security: SecurityPolicy | dict[str, Any] | None,
    has_tenant: bool = False,
) -> SecurityPolicy | None:
    if isinstance(security, SecurityPolicy):
        if has_tenant and not security.enforce_tenant_isolation:
            return replace(security, enforce_tenant_isolation=True)
        return security
    if isinstance(security, dict):
        pol = SecurityPolicy(**security)
        if has_tenant:
            pol.enforce_tenant_isolation = True
        return pol
    if has_tenant:
        return SecurityPolicy(enforce_tenant_isolation=True)
    return None


def compile_to_sqlalchemy(
    spec: QuerySpec | dict[str, Any],
    *,
    dialect: str = "postgres",
    schema: dict[str, Any] | None = None,
    security: SecurityPolicy | dict[str, Any] | None = None,
    context: TenantContext | dict[str, Any] | str | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any], str]:
    """Compiles a QuerySpec into a `(sqlalchemy.TextClause, bind_params, raw_sql)` tuple."""
    sa = _get_sqlalchemy()
    tenant_ctx = _normalize_tenant_context(context)
    policy = _coerce_policy(security, has_tenant=tenant_ctx is not None)

    eff_caps: EngineCapabilities = (
        capabilities
        if isinstance(capabilities, EngineCapabilities)
        else (
            EngineCapabilities.from_dict(capabilities)
            if isinstance(capabilities, dict)
            else EngineCapabilities.default()
        )
    )

    spec_dict: dict[str, Any] = (
        asdict(spec)
        if is_dataclass(spec) and not isinstance(spec, type)
        else dict(spec)  # type: ignore[arg-type]
    )

    active_spec: Any = spec_dict
    if policy is not None or tenant_ctx is not None:
        active_spec = apply_security_policy(
            spec_dict,
            schema=schema,
            context=tenant_ctx,
            policy=policy,
        )

    compiler = QueryCompiler(
        active_spec,
        schema=schema,
        dialect=dialect,
        capabilities=eff_caps,
    )
    main_sql, params = compiler.compile()[0:2]
    val_res = validate_sql_ast(main_sql, dialect=dialect)
    if not val_res.get("valid") or not val_res.get("is_read_only"):
        violations = val_res.get("violations", ["Query failed AST safety validation."])
        raise SecurityError(f"Security violation: {'; '.join(violations)}")

    named_sql, bind_params = _to_named_parameters(main_sql, list(params))
    return sa.text(named_sql), bind_params, main_sql


class SQLAlchemyIntegration:
    """Turnkey integration binding Query-Builder to a SQLAlchemy Engine, Connection, or Session."""

    def __init__(
        self,
        bind: Any,
        *,
        metadata: Any = None,
        security: SecurityPolicy | dict[str, Any] | None = None,
        capabilities: EngineCapabilities | dict[str, Any] | None = None,
        dialect: str | None = None,
    ) -> None:
        sa = _get_sqlalchemy()
        if isinstance(bind, str):
            self.bind = sa.create_engine(bind)
        else:
            self.bind = bind

        self.metadata = metadata
        self.policy: SecurityPolicy | None = _coerce_policy(security, has_tenant=False)
        self.capabilities: EngineCapabilities = (
            capabilities
            if isinstance(capabilities, EngineCapabilities)
            else (
                EngineCapabilities.from_dict(capabilities)
                if isinstance(capabilities, dict)
                else EngineCapabilities.default()
            )
        )
        self.dialect_name: str = dialect or self._detect_dialect()

    def _detect_dialect(self) -> str:
        """Detects Query-Builder dialect name from the bound SQLAlchemy object."""
        target = self._get_engine_or_connection()
        sa_dialect = getattr(getattr(target, "dialect", None), "name", None)
        if isinstance(sa_dialect, str) and sa_dialect:
            return _DIALECT_MAP.get(sa_dialect.lower(), "postgres")
        return "postgres"

    def _get_engine_or_connection(self) -> Any:
        """Extracts an inspectable Engine or Connection from self.bind."""
        if hasattr(self.bind, "get_bind"):
            return self.bind.get_bind()
        if (
            hasattr(self.bind, "kw")
            and isinstance(self.bind.kw, dict)
            and "bind" in self.bind.kw
        ):
            return self.bind.kw["bind"]
        return self.bind

    def _filter_tables(self, data: dict[str, Any]) -> dict[str, Any]:
        """Filters schema snapshot tables according to configured SecurityPolicy."""
        if (
            self.policy is None
            or "tables" not in data
            or not isinstance(data["tables"], dict)
        ):
            return data
        filtered = dict(data["tables"])
        if self.policy.allowed_tables:
            allowed_lower = {t.lower() for t in self.policy.allowed_tables}
            filtered = {k: v for k, v in filtered.items() if k.lower() in allowed_lower}
        if self.policy.restricted_tables:
            restricted_lower = {t.lower() for t in self.policy.restricted_tables}
            filtered = {
                k: v for k, v in filtered.items() if k.lower() not in restricted_lower
            }
        res = dict(data)
        res["tables"] = filtered
        return res

    def introspect_schema(self) -> dict[str, Any]:
        """Introspects the SQLAlchemy Engine, Connection, or MetaData into a SchemaSnapshot dict."""
        sa = _get_sqlalchemy()
        if self.metadata is not None:
            reflected = _reflect_live_sqlalchemy(self.metadata)
            if reflected is not None:
                raw_dict: dict[str, Any] = {
                    "tables": reflected.to_dict(),
                    "capabilities": self.capabilities.to_dict(),
                }
                return self._filter_tables(raw_dict)

        target = self._get_engine_or_connection()
        inspector = sa.inspect(target)
        tables_dict: dict[str, Any] = {}
        all_fks: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        for table_name in inspector.get_table_names():
            pk_constraint = inspector.get_pk_constraint(table_name) or {}
            pk_cols_list = [
                str(c) for c in (pk_constraint.get("constrained_columns") or []) if c
            ]
            pk_cols = set(pk_cols_list)
            fk_list = inspector.get_foreign_keys(table_name) or []

            col_to_fk: dict[str, dict[str, Any]] = {}
            table_fks: list[dict[str, Any]] = []
            for fk in fk_list:
                constrained = fk.get("constrained_columns") or []
                referred_table = fk.get("referred_table")
                referred_cols = fk.get("referred_columns") or []
                if constrained and referred_table and referred_cols:
                    fk_entry = {
                        "table": table_name,
                        "column": constrained[0],
                        "foreign_table": referred_table,
                        "foreign_column": referred_cols[0],
                    }
                    col_to_fk[constrained[0]] = fk_entry
                    table_fks.append(fk_entry)
                    all_fks.append(fk_entry)
                    relationships.append(
                        {
                            "source_table": table_name,
                            "source_column": constrained[0],
                            "target_table": referred_table,
                            "target_column": referred_cols[0],
                        }
                    )

            cols_out: list[dict[str, Any]] = []
            has_user_id = False
            for col in inspector.get_columns(table_name):
                c_name = str(col.get("name", ""))
                if c_name == "user_id":
                    has_user_id = True
                c_type = str(col.get("type", "text")).lower()
                cols_out.append(
                    {
                        "name": c_name,
                        "data_type": c_type,
                        "is_nullable": bool(col.get("nullable", True)),
                        "is_primary": c_name in pk_cols,
                        "default": col.get("default"),
                        "comment": col.get("comment"),
                        "foreign_key": col_to_fk.get(c_name),
                    }
                )

            tables_dict[table_name] = {
                "name": table_name,
                "schema": "public",
                "columns": cols_out,
                "primary_keys": pk_cols_list,
                "foreign_keys": table_fks,
                "has_user_id": has_user_id,
            }

        snapshot = {
            "tables": tables_dict,
            "foreign_keys": all_fks,
            "relationships": relationships,
            "capabilities": self.capabilities.to_dict(),
        }
        return self._filter_tables(snapshot)

    def compile(
        self,
        spec: QuerySpec | dict[str, Any],
        *,
        dialect: str | None = None,
        context: TenantContext | dict[str, Any] | str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any], str]:
        """Compiles a QuerySpec into `(sqlalchemy.TextClause, bind_params, raw_sql)`."""
        return compile_to_sqlalchemy(
            spec,
            dialect=dialect or self.dialect_name,
            schema=schema,
            security=self.policy,
            context=context,
            capabilities=self.capabilities,
        )

    def _execute_clause(
        self, clause: Any, bind_params: dict[str, Any]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Executes a SQLAlchemy TextClause against Engine, Connection, Session, or sessionmaker."""
        target = self.bind
        if callable(target) and not hasattr(target, "execute"):
            with target() as session:
                res = session.execute(clause, bind_params)
                cols = list(res.keys())
                rows = [dict(zip(cols, row, strict=False)) for row in res.fetchall()]
                return cols, rows

        if hasattr(target, "connect") and not hasattr(target, "execute"):
            with target.connect() as conn:
                res = conn.execute(clause, bind_params)
                cols = list(res.keys())
                rows = [dict(zip(cols, row, strict=False)) for row in res.fetchall()]
                return cols, rows

        res = target.execute(clause, bind_params)
        cols = list(res.keys())
        rows = [dict(zip(cols, row, strict=False)) for row in res.fetchall()]
        return cols, rows

    def execute(
        self,
        spec: QuerySpec | dict[str, Any],
        *,
        context: TenantContext | dict[str, Any] | str | None = None,
        schema: dict[str, Any] | None = None,
        statement_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Compiles and executes a QuerySpec against the bound SQLAlchemy engine/session."""
        _ = statement_timeout_ms
        spec_dict: dict[str, Any] = (
            asdict(spec)
            if is_dataclass(spec) and not isinstance(spec, type)
            else dict(spec)  # type: ignore[arg-type]
        )
        if spec_dict.get("ctes"):
            self.capabilities.require_feature("ctes")
        if spec_dict.get("window_functions"):
            self.capabilities.require_feature("window_functions")
        if (
            spec_dict.get("rollup")
            or spec_dict.get("cube")
            or spec_dict.get("grouping_sets")
            or spec_dict.get("pivot")
        ):
            self.capabilities.require_feature("analytical_grouping")
        if spec_dict.get("vector_search") or spec_dict.get("hybrid_search"):
            self.capabilities.require_feature("vector_search")

        clause, bind_params, raw_sql = self.compile(
            spec_dict,
            dialect=self.dialect_name,
            context=context,
            schema=schema,
        )
        t0 = time.perf_counter()
        cols, rows = self._execute_clause(clause, bind_params)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        raw_limit = spec_dict.get("limit")
        limit_val = int(raw_limit) if isinstance(raw_limit, int) else 50
        raw_offset = spec_dict.get("offset")
        offset_val = int(raw_offset) if isinstance(raw_offset, int) else 0

        return {
            "sql": raw_sql,
            "params": list(bind_params.values()),
            "columns": cols,
            "rows": rows,
            "count": len(rows),
            "limit": limit_val,
            "offset": offset_val,
            "latency_ms": latency_ms,
            "dialect": self.dialect_name,
        }

    def execute_raw(
        self,
        sql: str,
        params: dict[str, Any] | list[Any] | None = None,
        *,
        context: TenantContext | dict[str, Any] | str | None = None,
        allowed_schemas: list[str] | None = None,
        statement_timeout_ms: int | None = None,
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        """Validates AST safety and executes read-only raw SQL."""
        _ = statement_timeout_ms
        sa = _get_sqlalchemy()
        if not self.capabilities.is_enabled("raw_sql"):
            raise SecurityError("Feature 'raw_sql' is disabled in engine capabilities.")
        tenant_ctx = _normalize_tenant_context(context)
        if tenant_ctx is not None or (
            self.policy is not None and self.policy.enforce_tenant_isolation
        ):
            raise SecurityError(
                "Raw SQL execution is restricted when tenant isolation is enforced."
            )

        val_res = validate_sql_ast(
            sql, dialect=self.dialect_name, allowed_schemas=allowed_schemas
        )
        if not val_res.get("valid") or not val_res.get("is_read_only"):
            violations = val_res.get(
                "violations", ["Query failed AST safety validation."]
            )
            raise SecurityError(f"Security violation: {'; '.join(violations)}")

        if isinstance(params, dict):
            clause = sa.text(sql)
            bind_params = params
        elif isinstance(params, list):
            named_sql, bind_params = _to_named_parameters(sql, params)
            clause = sa.text(named_sql)
        else:
            clause = sa.text(sql)
            bind_params = {}

        t0 = time.perf_counter()
        cols, rows = self._execute_clause(clause, bind_params)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return cols, rows, latency_ms


def create_sqlalchemy_integration(
    bind: Any,
    *,
    metadata: Any = None,
    security: SecurityPolicy | dict[str, Any] | None = None,
    capabilities: EngineCapabilities | dict[str, Any] | None = None,
    dialect: str | None = None,
) -> SQLAlchemyIntegration:
    """Factory function creating a configured SQLAlchemyIntegration instance."""
    return SQLAlchemyIntegration(
        bind,
        metadata=metadata,
        security=security,
        capabilities=capabilities,
        dialect=dialect,
    )


__all__ = [
    "SQLAlchemyIntegration",
    "compile_to_sqlalchemy",
    "create_sqlalchemy_integration",
]
