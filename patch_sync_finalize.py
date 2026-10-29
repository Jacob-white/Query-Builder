with open("query_builder/connectors/base.py", "r") as f:
    content = f.read()

finalize_helper = """
    def _finalize_execution_result_sync(
        self,
        process_res: dict[str, Any],
        sec: SecurityConfig,
        pipeline: MiddlewarePipeline,
        ctx: dict[str, Any],
        user_id: Any,
        use_cache: bool,
        cache_key: str | None,
        cache_ttl: int,
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
                t_ctx and any(str(r).lower() == "admin" for r in getattr(t_ctx, "roles", []))
            )
            if not is_admin:
                compiled_pats = [re.compile(p) for p in sec.privacy.sensitive_column_patterns]
                strat = sec.privacy.masking_strategy
                masked_rows = []
                for row in dict_rows:
                    if isinstance(row, dict):
                        row_copy = dict(row)
                        for col_k, col_v in row_copy.items():
                            if any(p.search(str(col_k)) for p in compiled_pats):
                                row_copy[col_k] = apply_column_masking(col_v, strategy=strat)
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

        raw_result["cached"] = False
        if use_cache and cache_key is not None:
            from query_builder.cache import get_global_cache
            get_global_cache().set(cache_key, raw_result, ttl=cache_ttl)

        return pipeline.run_post_execute(raw_result, ctx)
"""

content = content.replace("    def execute(", finalize_helper + "\n    def execute(")
with open("query_builder/connectors/base.py", "w") as f:
    f.write(content)
