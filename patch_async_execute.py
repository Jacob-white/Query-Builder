with open("query_builder/connectors/async_base.py", "r") as f:
    content = f.read()

import re

# Find the start of execute body
execute_start = re.search(r'    async def execute\([^)]+\)\s*->\s*dict\[str,\s*Any\]:\s*"""[^"]+"""', content, re.DOTALL)
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

        spec_table = "unknown"
        try:
            if spec is None:
                short_circuited, process_res = await self._process_raw_query_async(
                    sql, params, sec, validate_ast, pipeline, ctx, timeout
                )
            else:
                short_circuited, process_res = await self._process_spec_query_async(
                    spec, schema, user_id, sec, validate_ast, pipeline, ctx, timeout, kwargs
                )

            if short_circuited:
                return process_res

            spec_table = process_res.get("spec_table", "unknown")
            return self._finalize_execution_result_async(
                process_res, sec, pipeline, ctx, user_id
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
with open("query_builder/connectors/async_base.py", "w") as f:
    f.write(new_content)
