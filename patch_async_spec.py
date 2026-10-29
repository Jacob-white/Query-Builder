with open("query_builder/connectors/async_base.py", "r") as f:
    content = f.read()

spec_query_helper = """
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
        if sec.execution.max_join_depth > 0 and len(joins) > sec.execution.max_join_depth:
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
"""

content = content.replace("    async def execute(", spec_query_helper + "\n    async def execute(")
with open("query_builder/connectors/async_base.py", "w") as f:
    f.write(content)
