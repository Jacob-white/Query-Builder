"""
Asynchronous Database Connector Specification and Execution Protocol.
======================================================================
Defines the abstract base class for asynchronous database connectors, supporting
async/await transaction boundaries, statement timeouts, schema introspection fallbacks,
lifecycle middleware pipeline execution, and security governance boundaries.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import re
import time
import types
from abc import ABC, abstractmethod
from typing import Any, Self

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.config import SecurityConfig, get_security_config
from query_builder.connectors.base import (
    _EGRESS_GUARDED_METHODS,
    ConnectionFailedError,
    IntrospectionError,
    as_connector_error,
    effective_network_config,
)
from query_builder.dialects import BaseDialect, get_dialect
from query_builder.egress_guard import egress_guard
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
    _is_mutating_sql,
)
from query_builder.models import QuerySpec
from query_builder.security import (
    SecurityError,
    apply_column_masking,
    calculate_ast_complexity,
    check_cartesian_products,
    collect_target_config,
    resolve_and_validate_target,
    scrub_secrets,
    validate_network_target,
)
from query_builder.telemetry import TelemetryCollector


def _egress_guarded(fn: Any) -> Any:
    if getattr(fn, "_egress_guarded", False):
        return fn

    @functools.wraps(fn)
    async def guarded(self: Any, *args: Any, **kw: Any) -> Any:
        with egress_guard(self._network_policy_config()):
            return await fn(self, *args, **kw)

    guarded._egress_guarded = True  # type: ignore[attr-defined]
    return guarded


class AsyncBaseConnector(ABC):
    """
    Abstract base asynchronous database connector providing standardized query compilation,
    async transaction execution, statement timeout guards, schema introspection,
    and automated security sandboxing boundaries.
    """

    dialect_name: str = "postgres"
    default_timeout_ms: int = 5000

    #: See ``BaseConnector.read_only_support``.
    read_only_support: str = "none"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "execute_raw" in cls.__dict__:
            orig_raw = cls.execute_raw
            if not getattr(orig_raw, "_error_mapped", False):

                @functools.wraps(orig_raw)
                async def mapped_execute_raw(self: Any, *args: Any, **kw: Any) -> Any:
                    try:
                        return await orig_raw(self, *args, **kw)
                    except Exception as exc:
                        mapped = as_connector_error(exc)
                        if mapped is exc:
                            raise
                        raise mapped from exc

                mapped_execute_raw._error_mapped = True  # type: ignore[attr-defined]
                cls.execute_raw = mapped_execute_raw  # type: ignore[method-assign]
        if "connect" in cls.__dict__:
            orig_connect = cls.connect
            if not getattr(orig_connect, "_security_wrapped", False):

                @functools.wraps(orig_connect)
                async def wrapped_async_connect(
                    self: Any, *args: Any, **kw: Any
                ) -> Any:
                    self._validate_network_target()
                    await self._pin_network_target()
                    try:
                        with egress_guard(self._network_policy_config()):
                            conn = await orig_connect(self, *args, **kw)
                            await self._ensure_read_only(conn)
                        return conn
                    except Exception as exc:
                        scrubbed = self._scrub_exception(exc)
                        if scrubbed is exc:
                            raise
                        if scrubbed.__cause__ is not None:
                            raise scrubbed from scrubbed.__cause__
                        raise scrubbed from None

                wrapped_async_connect._security_wrapped = True  # type: ignore[attr-defined]
                cls.connect = wrapped_async_connect  # type: ignore[method-assign]  # intentional wrap
        for name in _EGRESS_GUARDED_METHODS:
            fn = cls.__dict__.get(name)
            if inspect.iscoroutinefunction(fn) and not getattr(
                fn, "_egress_guarded", False
            ):
                setattr(cls, name, _egress_guarded(fn))

    def __init__(
        self,
        connection: Any = None,
        dialect: str | BaseDialect | None = None,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
        security: SecurityConfig | None = None,
        **config: Any,
    ) -> None:
        self._connection = connection
        self.config = config
        self.middleware = MiddlewarePipeline.ensure(middleware)
        self.telemetry_collector: TelemetryCollector = TelemetryCollector()

        self._explicit_security: bool = security is not None
        self.security: SecurityConfig = (
            security if security is not None else get_security_config()
        )

        if dialect is not None:
            self.dialect = (
                dialect if isinstance(dialect, BaseDialect) else get_dialect(dialect)
            )
            self.dialect_name = self.dialect.name
        else:
            self.dialect = get_dialect(self.dialect_name)

    def __repr__(self) -> str:
        mask = (
            getattr(self, "security", None) is None
            or self.security.logging.mask_credentials
        )
        patterns = (
            self.security.logging.sensitive_key_patterns
            if getattr(self, "security", None)
            else None
        )
        safe_config = (
            scrub_secrets(self.config, patterns=patterns) if mask else self.config
        )
        return f"<{self.__class__.__name__}(dialect={self.dialect_name!r}, config={safe_config!r})>"

    def __str__(self) -> str:
        mask = (
            getattr(self, "security", None) is None
            or self.security.logging.mask_credentials
        )
        patterns = (
            self.security.logging.sensitive_key_patterns
            if getattr(self, "security", None)
            else None
        )
        safe_config = (
            scrub_secrets(self.config, patterns=patterns) if mask else self.config
        )
        return f"{self.__class__.__name__}(dialect={self.dialect_name}, config={safe_config})"

    @property
    def effective_network_config(self) -> Any:
        return effective_network_config(self, self.security)

    def _network_policy_config(self) -> Any:
        """The network policy the egress guard enforces for this connector (or ``None``)."""
        return effective_network_config(self)

    def _network_context(
        self, security_config: SecurityConfig | None
    ) -> tuple[Any, dict[str, Any]] | None:
        net_cfg = effective_network_config(self, security_config)
        if net_cfg is None:
            return None

        target_config = collect_target_config(self)

        return net_cfg, target_config

    def _validate_network_target(
        self, security_config: SecurityConfig | None = None
    ) -> None:
        ctx = self._network_context(security_config)
        if ctx is None:
            return
        net_cfg, target_config = ctx
        validate_network_target(
            config=target_config,
            network_config=net_cfg,
        )

    async def _pin_network_target(self) -> None:
        """Resolves the configured host ONCE asynchronously, validates every address, and remembers
        the validated address in ``self._pinned_target`` for the connector to connect to.
        """
        self._pinned_target = None
        ctx = self._network_context(None)
        if ctx is None:
            return
        net_cfg, target_config = ctx
        if not getattr(net_cfg, "pin_resolved_addresses", True):
            return
        host = None
        for key in ("host", "hostname", "server"):
            if isinstance(target_config.get(key), str) and target_config[key].strip():
                host = target_config[key].strip()
                break
        if host is None or "://" in host:
            return
        port = target_config.get("port")
        try:
            port = int(port) if port is not None else None
        except (TypeError, ValueError):
            return

        self._pinned_target = resolve_and_validate_target(
            host,
            port,
            net_cfg,
            resolver=getattr(self, "_dns_resolver", None),
            fail_closed=bool(getattr(net_cfg, "fail_closed_on_dns_error", False)),
        )

    def pinned_connect_config(self, address_key: str = "hostaddr") -> dict[str, Any]:
        """``self.config`` plus ``address_key=<validated IP>`` when the host was pinned.

        For drivers that accept a separate numeric address next to the hostname: the
        hostname is still used for TLS verification, but no DNS lookup happens at connect time.
        """
        cfg = dict(self.config)
        target = getattr(self, "_pinned_target", None)
        if target is not None and target.pinned_address and not cfg.get(address_key):
            cfg[address_key] = target.pinned_address
        return cfg

    def validate_network(self, security_config: SecurityConfig | None = None) -> None:
        """Validates network egress target against active network security policy."""
        self._validate_network_target(security_config)

    def _scrub_exception(
        self,
        exc: Exception,
        security_config: SecurityConfig | None = None,
    ) -> Exception:
        """Sanitizes exception messages and causes so sensitive credentials are never leaked."""
        sec = security_config or getattr(self, "security", None)
        if sec and not sec.logging.mask_credentials:
            return exc

        patterns = sec.logging.sensitive_key_patterns if sec else None
        clean_msg = scrub_secrets(str(exc), patterns=patterns)

        has_dirty_cause = False
        if exc.__cause__ is not None:
            clean_cause_msg = scrub_secrets(str(exc.__cause__), patterns=patterns)
            has_dirty_cause = clean_cause_msg != str(exc.__cause__)

        if clean_msg == str(exc) and not has_dirty_cause:
            return exc

        exc_cls = type(exc)
        try:
            new_exc = exc_cls(clean_msg)
        except Exception:  # noqa: BLE001
            new_exc = ConnectionFailedError(clean_msg)

        if exc.__cause__ is not None:
            clean_cause_msg = scrub_secrets(str(exc.__cause__), patterns=patterns)
            cause_cls = type(exc.__cause__)
            try:
                new_cause = cause_cls(clean_cause_msg)
            except Exception:  # noqa: BLE001
                new_cause = Exception(clean_cause_msg)
            new_exc.__cause__ = new_cause
        else:
            new_exc.__cause__ = None

        new_exc.__traceback__ = exc.__traceback__
        return new_exc

    @abstractmethod
    async def connect(self) -> Any:
        """Establishes or returns an active database connection asynchronously."""

    async def apply_read_only(self, connection: Any) -> None:
        """Hook: make ``connection`` refuse writes at the database (see the sync base)."""
        return None

    async def _ensure_read_only(self, connection: Any) -> None:
        if connection is None:
            return
        sec = getattr(self, "security", None)
        if sec is None or not sec.execution.enforce_read_only_session:
            return
        if getattr(self, "_read_only_applied_to", None) is connection:
            return
        await self.apply_read_only(connection)
        self._read_only_applied_to = connection

    async def close(self) -> None:
        """Closes the active connection if managed by this connector."""
        if self._connection is not None:
            try:
                if hasattr(self._connection, "close"):
                    res = self._connection.close()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception:  # noqa: BLE001, S110
                pass
            finally:
                self._connection = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.close()

    async def test_connection(self) -> dict[str, Any]:
        """Validates connection health and returns dialect and engine metadata."""
        start = time.perf_counter()
        await self.execute_raw("SELECT 1")
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        """Default async schema introspection fallback returning normalized snapshot."""
        from query_builder.schema import normalize_schema_snapshot

        return normalize_schema_snapshot(
            {"tables": {}, "foreign_keys": [], "relationships": []},
            filter_sensitive=filter_sensitive,
        )

    async def _introspect_blocking(
        self,
        introspect: Any,
        label: str,
        schema_name: str | None,
        filter_sensitive: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a synchronous ``introspect_*(cursor, ...)`` helper against this connector's
        DB-API connection in a worker thread.

        For async connectors whose driver is blocking DB-API: without an override they would
        inherit the empty default snapshot above and silently report "no tables".
        """
        conn = await self.connect()

        def work() -> dict[str, Any]:
            cur = conn.cursor()
            try:
                return introspect(
                    cur,
                    schema_name=schema_name,
                    filter_sensitive=filter_sensitive,
                    **kwargs,
                )
            finally:
                close = getattr(cur, "close", None)
                if close is not None:
                    close()

        try:
            return await asyncio.to_thread(work)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect {label} schema '{schema_name}': {exc}"
            ) from exc

    async def inspect_tables(self) -> list[str]:
        """Returns a sorted list of table names in the database schema asynchronously."""
        snapshot = await self.introspect_schema()
        return sorted(snapshot.get("tables", {}).keys())

    async def inspect_columns(self, table_name: str) -> list[dict[str, Any]]:
        """Returns column metadata dictionaries for the specified table asynchronously."""
        snapshot = await self.introspect_schema()
        table_meta = snapshot.get("tables", {}).get(table_name)
        if not table_meta:
            return []
        return table_meta.get("columns", [])

    async def inspect_primary_keys(self, table_name: str) -> list[str]:
        """Returns the primary key column names for the specified table asynchronously."""
        cols = await self.inspect_columns(table_name)
        return [c["name"] for c in cols if c.get("is_primary")]

    async def inspect_foreign_keys(
        self, table_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Returns foreign key relationships, optionally filtered by table asynchronously."""
        snapshot = await self.introspect_schema()
        fks = snapshot.get("foreign_keys", [])
        if table_name is not None:
            return [fk for fk in fks if fk.get("table") == table_name]
        return fks

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        """Executes a raw SQL statement asynchronously against the database."""
        raise NotImplementedError("Subclasses must implement execute_raw()")

    async def _process_raw_query_async(
        self,
        sql: str | None,
        params: list[Any] | None,
        sec: SecurityConfig,
        validate_ast: bool,
        pipeline: MiddlewarePipeline,
        ctx: dict[str, Any],
        timeout: int | None,
    ) -> tuple[bool, Any]:
        if sql is None:
            raise CompilationError(
                "Specification must be a dictionary or dataclass instance."
            )
        main_sql = sql
        main_params = params or []
        count_sql = ""
        count_params: list[Any] = []
        compiled_spec: dict[str, Any] = {
            "table": "raw_query",
            "limit": 50,
            "offset": 0,
        }

        if sec.execution.enforce_read_only_session and _is_mutating_sql(main_sql):
            raise SecurityError(
                f"Read-only session violation: mutating statement detected in '{main_sql[:60]}'."
            )

        if validate_ast and sec.validation.validate_ast:
            v_res = validate_sql_ast(main_sql, dialect=self.dialect_name)
            if not v_res["valid"]:
                raise SecurityError(
                    f"Generated query failed AST safety validation: {v_res['message']}"
                )

        execution_plan = {
            "main_sql": main_sql,
            "main_params": main_params,
            "count_sql": count_sql,
            "count_params": count_params,
            "spec": compiled_spec,
        }
        short_circuited, result_or_plan = pipeline.run_pre_execute(execution_plan, ctx)
        if short_circuited:
            return True, pipeline.run_post_execute(result_or_plan, ctx)

        timeout_sec = timeout / 1000.0 if timeout else None
        try:
            col_names, dict_rows, latency_ms = await asyncio.wait_for(
                self.execute_raw(main_sql, main_params),
                timeout=timeout_sec,
            )
        except TimeoutError as exc:
            raise TimeoutError(f"Query execution timed out after {timeout}ms") from exc

        return False, {
            "main_sql": main_sql,
            "main_params": main_params,
            "compiled_spec": compiled_spec,
            "col_names": col_names,
            "dict_rows": dict_rows,
            "latency_ms": latency_ms,
            "total_count": len(dict_rows),
            "spec_table": "unknown",
        }

    async def _process_spec_query_async(
        self,
        spec: Any,
        schema: dict[str, Any] | None,
        user_id: Any,
        sec: SecurityConfig,
        validate_ast: bool,
        pipeline: MiddlewarePipeline,
        ctx: dict[str, Any],
        timeout: int | None,
        kwargs: dict[str, Any],
    ) -> tuple[bool, Any]:
        if not isinstance(spec, dict) and not hasattr(spec, "__dict__"):
            raise CompilationError(
                "Specification must be a dictionary or dataclass instance."
            )

        spec_dict = (
            dict(spec)
            if isinstance(spec, dict)
            else {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
        )
        spec_table = spec_dict.get("table", "unknown")

        complexity = calculate_ast_complexity(spec_dict)
        ctx["ast_complexity"] = complexity
        if (
            sec.execution.max_complexity_score > 0
            and complexity > sec.execution.max_complexity_score
        ):
            raise SecurityError(
                f"AST complexity score ({complexity}) exceeds maximum allowed limit ({sec.execution.max_complexity_score})."
            )
        if sec.execution.prevent_cartesian_products:
            check_cartesian_products(spec_dict)
        joins = spec_dict.get("joins", [])
        if (
            sec.execution.max_join_depth > 0
            and len(joins) > sec.execution.max_join_depth
        ):
            raise SecurityError(
                f"Query join depth ({len(joins)}) exceeds maximum allowed limit ({sec.execution.max_join_depth})."
            )
        spec_limit = spec_dict.get("limit")
        if spec_limit is None or int(spec_limit) > sec.execution.max_rows_limit:
            spec_dict["limit"] = sec.execution.max_rows_limit

        compiled_spec = pipeline.run_pre_compile(spec_dict, ctx)
        spec_table = compiled_spec.get("table", spec_table)

        resolved_tenant_id = kwargs.get(
            "tenant_id",
            compiled_spec.get("tenant_id")
            if isinstance(compiled_spec, dict)
            else getattr(compiled_spec, "tenant_id", None),
        )
        compiler = QueryCompiler(
            spec=compiled_spec,
            schema=schema,
            user_id=user_id,
            force_user_filter=bool(user_id),
            dialect=self.dialect,
            tenant_id=resolved_tenant_id,
        )
        main_sql, main_params, count_sql, count_params = compiler.compile()

        compilation: dict[str, Any] = {
            "main_sql": main_sql,
            "main_params": main_params,
            "count_sql": count_sql,
            "count_params": count_params,
        }
        compilation = pipeline.run_post_compile(compilation, ctx)
        main_sql = compilation["main_sql"]
        main_params = compilation["main_params"]
        count_sql = compilation["count_sql"]
        count_params = compilation["count_params"]

        if validate_ast:
            v_main = validate_sql_ast(main_sql, dialect=self.dialect_name)
            if not v_main["valid"]:
                raise SecurityError(
                    f"Generated query failed AST safety validation: {v_main['message']}"
                )
            v_count = validate_sql_ast(count_sql, dialect=self.dialect_name)
            if not v_count["valid"]:
                raise SecurityError(
                    f"Generated count query failed AST safety validation: {v_count['message']}"
                )

        if sec.execution.enforce_read_only_session:
            if main_sql and _is_mutating_sql(main_sql):
                raise SecurityError(
                    f"Read-only session violation: mutating statement detected in '{main_sql[:60]}'."
                )
            if count_sql and _is_mutating_sql(count_sql):
                raise SecurityError(
                    f"Read-only session violation: mutating statement detected in '{count_sql[:60]}'."
                )

        execution_plan = {
            "main_sql": main_sql,
            "main_params": main_params,
            "count_sql": count_sql,
            "count_params": count_params,
            "spec": compiled_spec,
        }

        short_circuited, result_or_plan = pipeline.run_pre_execute(execution_plan, ctx)
        if short_circuited:
            return True, pipeline.run_post_execute(result_or_plan, ctx)

        timeout_sec = timeout / 1000.0 if timeout else None
        try:
            _count_cols, count_rows, _ = await asyncio.wait_for(
                self.execute_raw(count_sql, count_params),
                timeout=timeout_sec,
            )
            total_count = 0
            if count_rows:
                first_row = count_rows[0]
                if isinstance(first_row, dict):
                    total_count = next(iter(first_row.values())) if first_row else 0
                else:
                    total_count = first_row[0] if len(first_row) > 0 else 0

            col_names, dict_rows, latency_ms = await asyncio.wait_for(
                self.execute_raw(main_sql, main_params),
                timeout=timeout_sec,
            )
        except TimeoutError as exc:
            raise TimeoutError(f"Query execution timed out after {timeout}ms") from exc

        return False, {
            "main_sql": main_sql,
            "main_params": main_params,
            "compiled_spec": compiled_spec,
            "col_names": col_names,
            "dict_rows": dict_rows,
            "latency_ms": latency_ms,
            "total_count": total_count,
            "spec_table": spec_table,
        }

    def _setup_execution_context(
        self,
        statement_timeout_ms: int | None,
        timeout_ms: int | None,
        security: SecurityConfig | None,
        context: dict[str, Any] | None,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None,
    ) -> tuple[SecurityConfig, int, dict[str, Any], MiddlewarePipeline]:
        sec = security or getattr(self, "security", None) or get_security_config()
        timeout = (
            timeout_ms
            if timeout_ms is not None
            else (
                statement_timeout_ms
                if statement_timeout_ms is not None
                else (sec.execution.statement_timeout_ms or self.default_timeout_ms)
            )
        )
        if timeout <= 0:
            raise ValueError("statement_timeout_ms must be positive.")

        ctx = context if context is not None else {}
        ctx.setdefault("statement_timeout_ms", timeout)
        ctx.setdefault("security", sec)

        pipeline = (
            MiddlewarePipeline.ensure(middleware)
            if middleware is not None
            else self.middleware
        )
        return sec, timeout, ctx, pipeline

    def _handle_execution_error(
        self,
        exc: Exception,
        sec: SecurityConfig,
        pipeline: MiddlewarePipeline,
        ctx: dict[str, Any],
        spec_table: str,
        user_id: Any,
    ) -> NoReturn:
        scrubbed_exc = self._scrub_exception(exc, security_config=sec)
        pipeline.run_error(scrubbed_exc, ctx)
        if sec and sec.logging.emit_audit_events:
            t_id = (
                getattr(ctx.get("tenant_context"), "tenant_id", None)
                if ctx is not None
                else None
            )
            self.telemetry_collector.record_audit_event(
                event_type="query_execution",
                action="execute",
                resource=str(spec_table),
                status="error",
                tenant_id=t_id,
                user_id=str(user_id) if user_id is not None else None,
                error_message=str(scrubbed_exc),
                details={"dialect": self.dialect_name},
            )
        if scrubbed_exc is exc:
            raise
        raise scrubbed_exc from None

    def _finalize_execution_result_async(
        self,
        process_res: dict[str, Any],
        sec: SecurityConfig,
        pipeline: MiddlewarePipeline,
        ctx: dict[str, Any],
        user_id: Any,
    ) -> dict[str, Any]:
        main_sql = process_res["main_sql"]
        main_params = process_res["main_params"]
        compiled_spec = process_res["compiled_spec"]
        col_names = process_res["col_names"]
        dict_rows = process_res["dict_rows"]
        latency_ms = process_res["latency_ms"]
        total_count = process_res["total_count"]
        spec_table = process_res["spec_table"]

        limit = int(compiled_spec.get("limit", 50))
        offset = int(compiled_spec.get("offset", 0))

        truncated = False
        if len(dict_rows) > sec.execution.max_rows_limit:
            dict_rows = dict_rows[: sec.execution.max_rows_limit]
            truncated = True

        if sec.privacy.sensitive_column_patterns and dict_rows:
            t_ctx = ctx.get("tenant_context")
            is_admin = bool(
                t_ctx
                and any(str(r).lower() == "admin" for r in getattr(t_ctx, "roles", []))
            )
            if not is_admin:
                compiled_pats = [
                    re.compile(p) for p in sec.privacy.sensitive_column_patterns
                ]
                strat = sec.privacy.masking_strategy
                masked_rows = []
                for row in dict_rows:
                    if isinstance(row, dict):
                        row_copy = dict(row)
                        for col_k, col_v in row_copy.items():
                            if any(p.search(str(col_k)) for p in compiled_pats):
                                row_copy[col_k] = apply_column_masking(
                                    col_v, strategy=strat
                                )
                        masked_rows.append(row_copy)
                    else:
                        masked_rows.append(row)
                dict_rows = masked_rows

        raw_result = {
            "sql": main_sql,
            "params": [str(p) for p in main_params],
            "columns": col_names,
            "rows": dict_rows,
            "count": total_count,
            "limit": limit,
            "offset": offset,
            "page": (offset // limit) + 1 if limit else 1,
            "latency_ms": round(latency_ms, 2),
            "dialect": self.dialect_name,
        }
        if truncated:
            raw_result["truncated"] = True

        if sec.logging.emit_audit_events:
            t_id = getattr(ctx.get("tenant_context"), "tenant_id", None)
            self.telemetry_collector.record_audit_event(
                event_type="query_execution",
                action="execute",
                resource=str(spec_table),
                status="success",
                tenant_id=t_id,
                user_id=str(user_id) if user_id is not None else None,
                details={
                    "dialect": self.dialect_name,
                    "row_count": len(dict_rows),
                    "total_count": total_count,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            self.telemetry_collector.record_execution(
                sql=main_sql,
                latency_ms=latency_ms,
                row_count=len(dict_rows),
                status="success",
                dialect=self.dialect_name,
                tenant_id=t_id,
                user_id=str(user_id) if user_id is not None else None,
                parameters=main_params,
                redact_parameters=sec.logging.redact_parameters,
            )

        return pipeline.run_post_execute(raw_result, ctx)

    async def execute(
        self,
        spec: dict[str, Any] | QuerySpec | None = None,
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        statement_timeout_ms: int | None = None,
        validate_ast: bool = True,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
        context: dict[str, Any] | None = None,
        *,
        sql: str | None = None,
        params: list[Any] | None = None,
        timeout_ms: int | None = None,
        security: SecurityConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Compiles a query specification into the connector's dialect, validates AST safety,
        and executes count and paginated data queries asynchronously with middleware hooks
        and security governance boundaries.
        """
        sec, timeout, ctx, pipeline = self._setup_execution_context(
            statement_timeout_ms, timeout_ms, security, context, middleware
        )

        spec_table = "unknown"
        try:
            if spec is None:
                short_circuited, process_res = await self._process_raw_query_async(
                    sql, params, sec, validate_ast, pipeline, ctx, timeout
                )
            else:
                short_circuited, process_res = await self._process_spec_query_async(
                    spec,
                    schema,
                    user_id,
                    sec,
                    validate_ast,
                    pipeline,
                    ctx,
                    timeout,
                    kwargs,
                )

            if short_circuited:
                return process_res

            spec_table = process_res.get("spec_table", "unknown")
            return self._finalize_execution_result_async(
                process_res, sec, pipeline, ctx, user_id
            )
        except Exception as exc:
            self._handle_execution_error(exc, sec, pipeline, ctx, spec_table, user_id)


for _name in _EGRESS_GUARDED_METHODS:
    _fn = AsyncBaseConnector.__dict__.get(_name)
    if inspect.iscoroutinefunction(_fn):
        setattr(AsyncBaseConnector, _name, _egress_guarded(_fn))
