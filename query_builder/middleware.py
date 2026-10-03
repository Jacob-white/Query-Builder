"""
Execution Lifecycle Middleware & Interceptor Pipeline.
======================================================
Provides pre-compile, post-compile, pre-execute, and post-execute hooks
for query rewriting, caching, audit logging, telemetry, and safe cancellation.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import Any, Self


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

    def on_error(self, error: Exception, context: dict[str, Any]) -> None:
        """Invoked whenever an exception is raised during compilation or execution."""


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
        if not isinstance(interceptor, LifecycleInterceptor):
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
        if isinstance(pipeline_or_items, LifecycleInterceptor):
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

    def run_error(self, error: Exception, context: dict[str, Any]) -> None:
        """Executes error hooks across all interceptors, suppressing secondary errors."""
        handled = context.setdefault("_handled_errors", set())
        if id(error) in handled:
            return
        handled.add(id(error))
        for interceptor in self.interceptors:
            with contextlib.suppress(Exception):
                interceptor.on_error(error, context)
