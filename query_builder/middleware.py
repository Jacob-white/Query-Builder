"""
Execution Lifecycle Middleware & Interceptor Pipeline.
======================================================
Provides pre-compile, post-compile, pre-execute, and post-execute hooks
for query rewriting, caching, audit logging, telemetry, security governance,
sandboxing, dynamic column masking, and safe cancellation.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Sequence
from typing import Any, Self

try:
    import sqlparse
except ImportError:
    sqlparse = None  # type: ignore[assignment]  # optional-import fallback; callers check for None

from query_builder._regex_utils import strip_block_comments
from query_builder.config import SecurityConfig, get_security_config
from query_builder.policy import (
    SecurityPolicy,
    TenantContext,
    apply_security_policy,
)
from query_builder.security import (
    SecurityError,
    apply_column_masking,
    calculate_ast_complexity,
    check_cartesian_products,
    scrub_secrets,
    validate_network_target,
)

MUTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "EXEC",
        "EXECUTE",
        "GRANT",
        "REVOKE",
    }
)


def _is_mutating_sql(sql: str) -> bool:
    """
    Checks if a SQL query contains mutating DDL/DML statements,
    ignoring string literals, comments, and column aliases.
    """
    if sqlparse is None:
        stripped = re.sub(r"'(?:''|\\[\s\S]|[^'\\])*'", "", sql)
        stripped = re.sub(r"--[^\n]*", "", stripped)
        stripped = strip_block_comments(stripped)
        for kw in MUTATION_KEYWORDS:
            if re.search(rf"\b{kw}\b", stripped, re.IGNORECASE):
                return True
        return False

    statements = sqlparse.parse(sql)
    for stmt in statements:
        if stmt.get_type() in (
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "ALTER",
            "CREATE",
            "TRUNCATE",
        ):
            return True

        prev_tok = None
        for tok in stmt.flatten():
            if (
                tok.is_whitespace
                or tok.ttype in sqlparse.tokens.Comment
                or tok.ttype in sqlparse.tokens.Literal.String
            ):
                continue
            val = tok.value.upper().strip('"[]`')
            if prev_tok and prev_tok.value.upper() == "AS":
                prev_tok = tok
                continue
            if val in MUTATION_KEYWORDS:
                return True
            prev_tok = tok

    return False


class QueryCancelledError(Exception):
    """Raised by middleware to safely cancel query execution or compilation."""

    def __init__(
        self,
        message: str = "Query execution cancelled by middleware.",
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class LifecycleInterceptor:
    """
    Base lifecycle interceptor interface.

    Subclasses override lifecycle hook methods to inspect, rewrite, or short-circuit queries.
    """

    def on_pre_compile(
        self, spec: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Invoked before the query specification is compiled into SQL."""
        return None

    def on_post_compile(
        self, compilation: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Invoked after query specification has been compiled into SQL."""
        return None

    def on_pre_execute(
        self, execution_plan: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Invoked immediately before database cursor execution.

        Returning a non-None dictionary immediately short-circuits execution (e.g. cache hits).
        """
        return None

    def on_post_execute(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Invoked after query results have been fetched and formatted."""
        return None

    def on_error(self, error: BaseException, context: dict[str, Any]) -> None:
        """Invoked whenever an exception is raised during compilation or execution."""


class SecurityMiddleware(LifecycleInterceptor):
    """
    Security lifecycle middleware connecting SecurityConfig to query compilation,
    execution boundaries, sandboxing, privacy masking, and telemetry.
    """

    def __init__(
        self,
        config: SecurityConfig | None = None,
        policy: SecurityPolicy | None = None,
        tenant_context: TenantContext | None = None,
    ) -> None:
        self.config: SecurityConfig = config or get_security_config()
        self.policy: SecurityPolicy | None = policy
        self.tenant_context: TenantContext | None = tenant_context

    def on_pre_compile(
        self, spec: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Enforces AST complexity, join depth, Cartesian product checks, and tenant isolation."""
        current_spec = dict(spec)

        # 1. AST complexity validation
        complexity = calculate_ast_complexity(current_spec)
        context["ast_complexity"] = complexity
        if (
            self.config.execution.max_complexity_score > 0
            and complexity > self.config.execution.max_complexity_score
        ):
            raise SecurityError(
                f"AST complexity score ({complexity}) exceeds maximum allowed limit ({self.config.execution.max_complexity_score})."
            )

        # 2. Cartesian product validation
        if self.config.execution.prevent_cartesian_products:
            check_cartesian_products(current_spec)

        # 3. Join depth validation
        joins = current_spec.get("joins", [])
        if (
            self.config.execution.max_join_depth > 0
            and len(joins) > self.config.execution.max_join_depth
        ):
            raise SecurityError(
                f"Query join depth ({len(joins)}) exceeds maximum allowed limit ({self.config.execution.max_join_depth})."
            )

        # 4. Row limit ceiling
        if self.config.execution.max_rows_limit > 0:
            limit = current_spec.get("limit")
            if limit is None or int(limit) > self.config.execution.max_rows_limit:
                current_spec["limit"] = self.config.execution.max_rows_limit

        # 5. Multi-tenant privacy policy application
        t_ctx = context.get("tenant_context") or self.tenant_context
        if self.config.privacy.enforce_tenant_isolation:
            active_pol = self.policy or SecurityPolicy(
                tenant_column=self.config.privacy.tenant_column,
                enforce_tenant_isolation=True,
                sensitive_column_patterns=self.config.privacy.sensitive_column_patterns,
                masking_strategy=self.config.privacy.masking_strategy,
            )
            current_spec = apply_security_policy(
                current_spec,
                schema=context.get("schema"),
                context=t_ctx,
                policy=active_pol,
            )

        return current_spec

    def on_post_compile(
        self, compilation: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Enforces read-only sessions, allowed statement types, CTE limits, and catalog protections."""
        main_sql = compilation.get("main_sql", "")
        sql_stripped = main_sql.strip()
        sql_upper = sql_stripped.upper()

        # 1. Read-only session & mutating keyword enforcement
        if (
            self.config.execution.enforce_read_only_session
            and sql_stripped
            and _is_mutating_sql(sql_stripped)
        ):
            raise SecurityError(
                f"Read-only session violation: mutating statement detected in '{main_sql[:60]}'."
            )

        # 2. Allowed statements validation
        if self.config.validation.allowed_statements:
            allowed = tuple(
                s.upper() for s in self.config.validation.allowed_statements
            )
            first_word = sql_upper.split()[0] if sql_upper.split() else ""
            if first_word and not any(
                first_word == s or (s == "SELECT" and first_word == "WITH")
                for s in allowed
            ):
                raise SecurityError(
                    f"Statement type '{first_word}' is not in allowed statements list: {self.config.validation.allowed_statements}."
                )

        # 3. CTE and Recursive CTE check
        if "WITH " in sql_upper or sql_upper.startswith("WITH "):
            if not self.config.validation.allow_cte:
                raise SecurityError(
                    "Common Table Expressions (CTEs) are forbidden by validation security configuration."
                )
            if (
                "RECURSIVE " in sql_upper
                and not self.config.validation.allow_recursive_cte
            ):
                raise SecurityError(
                    "Recursive CTEs are forbidden by validation security configuration."
                )

        # 4. System catalog access check
        if not self.config.validation.allow_system_catalogs:
            system_catalogs = (
                "pg_catalog",
                "information_schema",
                "sqlite_master",
                "sqlite_temp_master",
                "sqlite_schema",
                "sys.",
                "mysql.",
            )
            sql_lower = sql_stripped.lower()
            if any(cat in sql_lower for cat in system_catalogs):
                raise SecurityError(
                    "Access to system catalog tables is forbidden by validation security configuration."
                )

        # 5. Filter SQL comments if enabled
        if self.config.validation.filter_sql_comments and compilation.get("main_sql"):
            cleaned = re.sub(r"--[^\n]*", "", compilation["main_sql"])
            cleaned = strip_block_comments(cleaned)
            compilation["main_sql"] = cleaned.strip()

        return compilation

    def on_pre_execute(
        self, execution_plan: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Validates execution boundaries and network targets prior to cursor execution."""
        context["statement_timeout_ms"] = self.config.execution.statement_timeout_ms

        # Network target egress validation
        target_host = execution_plan.get("host") or context.get("host")
        target_port = execution_plan.get("port") or context.get("port")
        target_url = execution_plan.get("url") or context.get("url")
        target_cfg = (
            execution_plan.get("connection_config")
            or context.get("connection_config")
            or execution_plan
        )
        if target_host or target_url or target_cfg:
            validate_network_target(
                host=target_host,
                port=target_port,
                url=target_url,
                config=target_cfg,
                network_config=self.config.network,
            )

        return None

    def on_post_execute(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Applies server-side row ceilings and dynamic column masking on returned rows."""
        if not isinstance(result, dict):
            return None

        # 1. Truncate rows if exceeding max_rows_limit
        rows = result.get("rows")
        if (
            isinstance(rows, list)
            and self.config.execution.max_rows_limit > 0
            and len(rows) > self.config.execution.max_rows_limit
        ):
            result["rows"] = rows[: self.config.execution.max_rows_limit]
            result["truncated"] = True

        # 2. Dynamic column masking on returned rows
        rows = result.get("rows")
        if (
            isinstance(rows, list)
            and rows
            and self.config.privacy.sensitive_column_patterns
        ):
            t_ctx = context.get("tenant_context") or self.tenant_context
            is_admin = bool(
                t_ctx
                and any(r.lower() == "admin" for r in t_ctx.roles if isinstance(r, str))
            )
            if not is_admin:
                compiled_pats = [
                    re.compile(p) for p in self.config.privacy.sensitive_column_patterns
                ]
                strategy = self.config.privacy.masking_strategy
                masked_rows = []
                for row in rows:
                    if isinstance(row, dict):
                        row_copy = dict(row)
                        for col_name, col_val in row_copy.items():
                            if any(p.search(str(col_name)) for p in compiled_pats):
                                row_copy[col_name] = apply_column_masking(
                                    col_val, strategy=strategy
                                )
                        masked_rows.append(row_copy)
                    else:
                        masked_rows.append(row)
                result["rows"] = masked_rows

        return result

    def on_error(self, error: BaseException, context: dict[str, Any]) -> None:
        """Sanitizes exception messages in error contexts."""
        context["sanitized_error"] = scrub_secrets(str(error))


class MiddlewarePipeline:
    """Manages sequential execution of lifecycle interceptors."""

    def __init__(
        self, interceptors: Sequence[LifecycleInterceptor] | None = None
    ) -> None:
        self.interceptors: list[LifecycleInterceptor] = []
        if interceptors is not None:
            for interceptor in interceptors:
                self.add(interceptor)

    def add(self, interceptor: LifecycleInterceptor) -> Self:
        """Appends an interceptor to the pipeline chain."""
        if not isinstance(interceptor, LifecycleInterceptor) and not hasattr(
            interceptor, "on_pre_compile"
        ):
            raise TypeError(
                f"Expected LifecycleInterceptor, got {type(interceptor).__name__}"
            )
        self.interceptors.append(interceptor)
        return self

    @classmethod
    def ensure(cls, pipeline_or_items: Any) -> MiddlewarePipeline:
        """Normalizes an interceptor, list of interceptors, or existing pipeline into a MiddlewarePipeline."""
        if pipeline_or_items is None:
            return cls()
        if isinstance(pipeline_or_items, MiddlewarePipeline):
            return pipeline_or_items
        if isinstance(pipeline_or_items, LifecycleInterceptor) or hasattr(
            pipeline_or_items, "on_pre_compile"
        ):
            return cls([pipeline_or_items])
        if isinstance(pipeline_or_items, (list, tuple)):
            return cls(list(pipeline_or_items))
        raise TypeError(
            f"Cannot convert {type(pipeline_or_items).__name__} to MiddlewarePipeline"
        )

    def run_pre_compile(
        self, spec: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Executes pre-compile hooks sequentially."""
        current_spec = spec
        for interceptor in self.interceptors:
            res = interceptor.on_pre_compile(current_spec, context)
            if res is not None:
                if not isinstance(res, dict):
                    raise TypeError("on_pre_compile must return dict or None")
                current_spec = res
        return current_spec

    def run_post_compile(
        self, compilation: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Executes post-compile hooks sequentially."""
        current_compilation = compilation
        for interceptor in self.interceptors:
            res = interceptor.on_post_compile(current_compilation, context)
            if res is not None:
                if not isinstance(res, dict):
                    raise TypeError("on_post_compile must return dict or None")
                current_compilation = res
        return current_compilation

    def run_pre_execute(
        self, execution_plan: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, Any]:
        """
        Executes pre-execute hooks sequentially.

        Returns (True, cached_result) if any interceptor short-circuited execution,
        or (False, execution_plan) if execution should continue.
        """
        for interceptor in self.interceptors:
            res = interceptor.on_pre_execute(execution_plan, context)
            if res is not None:
                context["short_circuited"] = True
                return True, res
        return False, execution_plan

    def run_post_execute(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Executes post-execute hooks sequentially."""
        current_result = result
        for interceptor in self.interceptors:
            res = interceptor.on_post_execute(current_result, context)
            if res is not None:
                if not isinstance(res, dict):
                    raise TypeError("on_post_execute must return dict or None")
                current_result = res
        return current_result

    def run_error(self, error: BaseException, context: dict[str, Any]) -> None:
        """Executes error hooks across all interceptors, suppressing secondary errors."""
        handled = context.setdefault("_handled_errors", set())
        if id(error) in handled:
            return
        handled.add(id(error))
        for interceptor in self.interceptors:
            with contextlib.suppress(Exception):
                interceptor.on_error(error, context)
