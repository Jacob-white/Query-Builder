"""
Amazon DynamoDB PartiQL Query Connector.
========================================
Executes PartiQL SQL statements against Amazon DynamoDB tables using AWS SDK boto3.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from query_builder.ast_validator import (
    validate_sql_ast,
)
from query_builder.compiler import (
    CompilationError,
    QueryCompiler,
)
from query_builder.config import SecurityConfig
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
    SecurityError,
)
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
    _is_mutating_sql,
)
from query_builder.models import QuerySpec
from query_builder.schema import normalize_schema_snapshot
from query_builder.security import (
    apply_column_masking,
    calculate_ast_complexity,
    check_cartesian_products,
)


_DYNAMO_TYPES = {"S": "string", "N": "number", "B": "binary"}
_DYNAMO_VALUE_TYPES = {
    "S": "string",
    "N": "number",
    "B": "binary",
    "BOOL": "boolean",
    "NULL": "null",
    "L": "list",
    "M": "map",
    "SS": "string_set",
    "NS": "number_set",
    "BS": "binary_set",
}


def _dynamo_value_type(value: Any) -> str:
    if isinstance(value, dict) and value:
        return _DYNAMO_VALUE_TYPES.get(next(iter(value)), "string")
    return "string"


def _dynamo_number(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text)


class DynamoDBConnector(BaseConnector):
    """Connector for Amazon DynamoDB using PartiQL."""

    dialect_name = "dynamodb"

    def __init__(
        self,
        client: Any = None,
        region_name: str = "us-east-1",
        **config: Any,
    ) -> None:
        super().__init__(**config)
        self._client = client
        self._connection = client
        self.region_name = region_name

    def connect(self) -> Any:
        if self._client is not None:
            self._connection = self._client
            return self._client

        try:
            import boto3
        except ImportError as err:
            raise DriverNotInstalledError(
                "boto3 is not installed. Install with: pip install 'query-builder-engine[dynamodb]'"
            ) from err

        try:
            self._client = boto3.client(
                "dynamodb", region_name=self.region_name, **self.config
            )
            self._connection = self._client
            return self._client
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Amazon DynamoDB: {exc}"
            ) from exc

    def close(self) -> None:
        """Closes the client connection and releases resources."""
        if self._client is not None:
            with contextlib.suppress(Exception):
                getattr(self._client, "close", lambda: None)()
            self._client = None
        super().close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        client = self.connect()
        client.list_tables()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round(latency_ms, 2),
            "engine_version": "Amazon DynamoDB PartiQL",
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        client = self.connect()
        try:
            resp = client.list_tables()
            table_names = resp.get("TableNames", [])
            tables_map: dict[str, dict[str, Any]] = {}

            for tbl in table_names:
                desc = client.describe_table(TableName=tbl).get("Table", {})
                key_schema = {k["AttributeName"] for k in desc.get("KeySchema", [])}
                cols = []
                has_user = False

                declared: dict[str, str] = {
                    str(a["AttributeName"]): _DYNAMO_TYPES.get(
                        str(a.get("AttributeType", "S")), "string"
                    )
                    for a in desc.get("AttributeDefinitions", [])
                }
                # AttributeDefinitions only lists KEY attributes; every other attribute of
                # a schemaless item is discovered from a sample of the table.
                sampled: dict[str, str] = {}
                with contextlib.suppress(Exception):
                    scan = client.scan(TableName=tbl, Limit=100)
                    for item in scan.get("Items", []):
                        for a_name, a_val in item.items():
                            sampled.setdefault(
                                str(a_name), _dynamo_value_type(a_val)
                            )
                for attr_name, attr_type in {**sampled, **declared}.items():
                    if attr_name == "user_id":
                        has_user = True
                    key = attr_name in key_schema
                    cols.append(
                        {
                            "name": attr_name,
                            "data_type": attr_type,
                            "is_nullable": not key,
                            "is_primary": key,
                            "comment": None,
                        }
                    )

                tables_map[tbl] = {
                    "name": tbl,
                    "columns": cols,
                    "has_user_id": has_user,
                    "user_col": "user_id",
                    "comment": None,
                }

            return normalize_schema_snapshot(
                {"tables": tables_map, "foreign_keys": [], "relationships": []},
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect DynamoDB tables: {exc}"
            ) from exc

    @staticmethod
    def _to_dynamo_param(val: Any) -> dict[str, Any]:
        if isinstance(val, bool):
            return {"BOOL": val}
        if isinstance(val, (int, float)):
            return {"N": str(val)}
        if val is None:
            return {"NULL": True}
        return {"S": str(val)}

    @staticmethod
    def _unmarshal_value(v: Any) -> Any:
        if not isinstance(v, dict) or not v:
            return None
        if "S" in v:
            return v["S"]
        if "N" in v:
            return _dynamo_number(v["N"])
        if "BOOL" in v:
            return v["BOOL"]
        if "NULL" in v:
            return None
        if "L" in v:
            return [DynamoDBConnector._unmarshal_value(x) for x in v["L"]]
        if "M" in v:
            return {k: DynamoDBConnector._unmarshal_value(x) for k, x in v["M"].items()}
        if "SS" in v:
            return list(v["SS"])
        if "NS" in v:
            return [_dynamo_number(x) for x in v["NS"]]
        return next(iter(v.values()))  # B / BS: raw bytes

    @staticmethod
    def _unmarshal_item(item: dict[str, Any]) -> dict[str, Any]:
        return {k: DynamoDBConnector._unmarshal_value(v) for k, v in item.items()}

    def _fetch_items(
        self, client: Any, statement: str, params: list[Any], max_rows: int
    ) -> list[dict[str, Any]]:
        """Run a PartiQL statement and follow ``NextToken`` pages up to ``max_rows``."""
        kwargs: dict[str, Any] = {"Statement": statement}
        if params:
            kwargs["Parameters"] = [self._to_dynamo_param(p) for p in params]
        items: list[dict[str, Any]] = []
        while True:
            resp = client.execute_statement(**kwargs)
            items.extend(resp.get("Items", []))
            token = resp.get("NextToken")
            if not token or len(items) > max_rows:
                return items
            kwargs["NextToken"] = token

    def execute(
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
        sec = security or getattr(self, "security", None) or SecurityConfig()
        pipeline = MiddlewarePipeline(
            interceptors=middleware
            if isinstance(middleware, list)
            else (middleware.interceptors if middleware else None)
        )
        ctx = dict(context or {})
        ctx.setdefault("dialect", self.dialect_name)

        client = self.connect()

        try:
            start = time.perf_counter()
            if sql is not None:
                main_sql = sql
                main_params = params or []
                total_count = 0
                limit = 50
                offset = 0

                if sec.execution.enforce_read_only_session and _is_mutating_sql(
                    main_sql
                ):
                    raise SecurityError(
                        f"Read-only session violation: mutating statement detected in '{main_sql[:60]}'."
                    )

                if validate_ast and sec.validation.validate_ast:
                    v_res = validate_sql_ast(main_sql, dialect=self.dialect_name)
                    if not v_res["valid"]:
                        raise SecurityError(
                            f"Generated query failed AST safety validation: {v_res['message']}"
                        )

                items = self._fetch_items(
                    client, main_sql, main_params, sec.execution.max_rows_limit
                )
                rows = [self._unmarshal_item(it) for it in items]
                columns = list(
                    dict.fromkeys(k for r in rows for k in r)  # schemaless: union of keys
                )
                total_count = len(rows)
            else:
                if (
                    spec is not None
                    and not isinstance(spec, dict)
                    and not hasattr(spec, "__dict__")
                ):
                    raise CompilationError(
                        "Specification must be a dictionary or dataclass instance."
                    )
                if spec is None:
                    raise CompilationError(
                        "Specification must be a dictionary or dataclass instance."
                    )

                spec_dict = (
                    {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
                    if hasattr(spec, "__dict__") and not isinstance(spec, dict)
                    else dict(spec)
                )

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

                compiler = QueryCompiler(
                    spec=spec,
                    schema=schema,
                    user_id=user_id,
                    force_user_filter=bool(user_id),
                    dialect=self.dialect,
                )
                main_sql, main_params, count_sql, count_params = compiler.compile()

                if validate_ast:
                    v_main = validate_sql_ast(main_sql, dialect=self.dialect_name)
                    if not v_main["valid"]:
                        raise CompilationError(
                            f"Generated query failed AST safety validation: {v_main['message']}"
                        )
                    v_count = validate_sql_ast(count_sql, dialect=self.dialect_name)
                    if not v_count["valid"]:
                        raise CompilationError(
                            f"Generated count query failed AST safety validation: {v_count['message']}"
                        )

                # Total Count query
                total_count = 0
                try:
                    count_kwargs: dict[str, Any] = {"Statement": count_sql}
                    if count_params:
                        count_kwargs["Parameters"] = [
                            self._to_dynamo_param(p) for p in count_params
                        ]
                    count_resp = client.execute_statement(**count_kwargs)
                    count_items = count_resp.get("Items", [])
                    if count_items:
                        first_val = next(iter(count_items[0].values()), {})
                        if isinstance(first_val, dict) and "N" in first_val:
                            try:
                                total_count = int(first_val["N"])
                            except (ValueError, TypeError):
                                total_count = 0
                except Exception:  # noqa: BLE001
                    total_count = 0

                items = self._fetch_items(
                    client, main_sql, main_params, sec.execution.max_rows_limit
                )
                rows = [self._unmarshal_item(it) for it in items]
                columns = list(dict.fromkeys(k for r in rows for k in r))

                limit = int(spec_dict.get("limit", 50))
                offset = int(spec_dict.get("offset", 0))

            latency_ms = (time.perf_counter() - start) * 1000.0

            truncated = False
            if len(rows) > sec.execution.max_rows_limit:
                rows = rows[: sec.execution.max_rows_limit]
                truncated = True

            if sec.privacy.sensitive_column_patterns and rows:
                t_ctx = ctx.get("tenant_context")
                is_admin = bool(
                    t_ctx
                    and any(
                        str(r).lower() == "admin" for r in getattr(t_ctx, "roles", [])
                    )
                )
                if not is_admin:
                    compiled_pats = [
                        re.compile(p) for p in sec.privacy.sensitive_column_patterns
                    ]
                    strat = sec.privacy.masking_strategy
                    masked_rows = []
                    for row in rows:
                        row_copy = dict(row)
                        for col_k, col_v in row_copy.items():
                            if any(p.search(str(col_k)) for p in compiled_pats):
                                row_copy[col_k] = apply_column_masking(
                                    col_v, strategy=strat
                                )
                        masked_rows.append(row_copy)
                    rows = masked_rows

            raw_result = {
                "sql": main_sql,
                "params": [str(p) for p in main_params],
                "columns": columns,
                "rows": rows,
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
                    resource="raw_query"
                    if sql is not None
                    else str(spec_dict.get("table", "unknown")),
                    status="success",
                    tenant_id=t_id,
                    user_id=str(user_id) if user_id is not None else None,
                    details={
                        "dialect": self.dialect_name,
                        "row_count": len(rows),
                        "total_count": total_count,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
                self.telemetry_collector.record_execution(
                    sql=main_sql,
                    latency_ms=latency_ms,
                    row_count=len(rows),
                    status="success",
                    dialect=self.dialect_name,
                    tenant_id=t_id,
                    user_id=str(user_id) if user_id is not None else None,
                    parameters=main_params,
                    redact_parameters=sec.logging.redact_parameters,
                )

            return pipeline.run_post_execute(raw_result, ctx)

        except Exception as exc:  # noqa: BLE001
            scrubbed_exc = self._scrub_exception(exc, security_config=sec)
            pipeline.run_error(scrubbed_exc, ctx)
            if sec.logging.emit_audit_events:
                t_id = getattr(ctx.get("tenant_context"), "tenant_id", None)
                self.telemetry_collector.record_audit_event(
                    event_type="query_execution",
                    action="execute",
                    resource="query",
                    status="error",
                    tenant_id=t_id,
                    user_id=str(user_id) if user_id is not None else None,
                    details={"error": str(scrubbed_exc)},
                )
            raise scrubbed_exc from exc
