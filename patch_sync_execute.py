with open("query_builder/connectors/base.py", "r") as f:
    content = f.read()

import re

# Find the start of execute body
execute_start = re.search(r'    def execute\([^)]+\)\s*->\s*dict\[str,\s*Any\]:\s*"""[^"]+"""', content, re.DOTALL)
if not execute_start:
    print("Could not find start of execute()")
    exit(1)

# Find the end of execute method before the loop at the bottom
execute_end = re.search(r'    except Exception as exc:.*?raise scrubbed_exc from None', content, re.DOTALL)
if not execute_end:
    print("Could not find end of execute()")
    exit(1)

new_execute_body = """
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

        use_cache = kwargs.get("use_cache", sec.execution.enable_cache)
        cache_ttl = kwargs.get("cache_ttl", sec.execution.default_ttl_seconds)
        cache_key = None
        if use_cache:
            from query_builder.cache import compute_cache_key, get_global_cache

            target = spec if spec is not None else {"sql": sql, "params": params or []}
            cache_key = compute_cache_key(
                target, dialect=self.dialect_name, tenant_id=kwargs.get("tenant_id")
            )
            cached_res = get_global_cache().get(cache_key)
            if cached_res is not None and isinstance(cached_res, dict):
                res_copy = dict(cached_res)
                res_copy["cached"] = True
                return res_copy

        spec_table = "unknown"
        try:
            if spec is None:
                short_circuited, process_res = self._process_raw_query_sync(
                    sql, params, sec, validate_ast, pipeline, ctx, timeout
                )
            else:
                short_circuited, process_res = self._process_spec_query_sync(
                    spec, schema, user_id, sec, validate_ast, pipeline, ctx, timeout, kwargs
                )

            if short_circuited:
                return process_res

            spec_table = process_res.get("spec_table", "unknown")
            return self._finalize_execution_result_sync(
                process_res, sec, pipeline, ctx, user_id, use_cache, cache_key, cache_ttl
            )

        except Exception as exc:
            scrubbed_exc = self._scrub_exception(exc, security_config=sec)
            pipeline.run_error(scrubbed_exc, ctx)
            if sec and sec.logging.emit_audit_events:
                t_id = getattr(ctx.get("tenant_context"), "tenant_id", None) if "ctx" in locals() else None
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
"""

start_pos = execute_start.end()
end_pos = execute_end.end()

new_content = content[:start_pos] + new_execute_body + content[end_pos:]
with open("query_builder/connectors/base.py", "w") as f:
    f.write(new_content)
