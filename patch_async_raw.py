import re

with open("query_builder/connectors/async_base.py", "r") as f:
    content = f.read()

# Let's write the _process_raw_query_async helper
raw_query_helper = """
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
"""

content = content.replace("    async def execute(", raw_query_helper + "\n    async def execute(")
with open("query_builder/connectors/async_base.py", "w") as f:
    f.write(content)
