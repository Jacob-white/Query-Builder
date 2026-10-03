"""
Amazon DynamoDB PartiQL Query Connector.
========================================
Executes PartiQL SQL statements against Amazon DynamoDB tables using AWS SDK boto3.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.schema import normalize_schema_snapshot


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
        self.region_name = region_name

    def connect(self) -> Any:
        if self._client is not None:
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
            return self._client
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Amazon DynamoDB: {exc}"
            ) from exc

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

                for attr in desc.get("AttributeDefinitions", []):
                    attr_name = str(attr["AttributeName"])
                    if attr_name == "user_id":
                        has_user = True
                    cols.append(
                        {
                            "name": attr_name,
                            "data_type": str(attr.get("AttributeType", "S")).lower(),
                            "is_nullable": False,
                            "is_primary": attr_name in key_schema,
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
    def _unmarshal_item(item: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for k, v in item.items():
            if "S" in v:
                out[k] = v["S"]
            elif "N" in v:
                val = v["N"]
                out[k] = float(val) if "." in val else int(val)
            elif "BOOL" in v:
                out[k] = v["BOOL"]
            elif "NULL" in v:
                out[k] = None
            else:
                out[k] = next(iter(v.values())) if v else None
        return out

    def execute(
        self,
        spec: dict[str, Any],
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        statement_timeout_ms: int | None = None,
        validate_ast: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(spec, dict) and not hasattr(spec, "__dict__"):
            raise CompilationError(
                "Specification must be a dictionary or dataclass instance."
            )

        client = self.connect()
        compiler = QueryCompiler(
            spec=spec,
            schema=schema,
            user_id=user_id,
            force_user_filter=bool(user_id),
            dialect=self.dialect,
        )
        main_sql, main_params, count_sql, count_params = compiler.compile()

        if validate_ast:
            v_main = validate_sql_ast(main_sql)
            if not v_main["valid"]:
                raise CompilationError(
                    f"Generated query failed AST safety validation: {v_main['message']}"
                )
            v_count = validate_sql_ast(count_sql)
            if not v_count["valid"]:
                raise CompilationError(
                    f"Generated count query failed AST safety validation: {v_count['message']}"
                )

        # 1. Total Count query
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
                    total_count = int(first_val["N"])
        except Exception:  # noqa: BLE001
            total_count = 0

        # 2. Main query
        start = time.perf_counter()
        exec_kwargs: dict[str, Any] = {"Statement": main_sql}
        if main_params:
            exec_kwargs["Parameters"] = [self._to_dynamo_param(p) for p in main_params]
        resp = client.execute_statement(**exec_kwargs)
        latency_ms = (time.perf_counter() - start) * 1000.0

        items = resp.get("Items", [])
        rows = [self._unmarshal_item(it) for it in items]
        columns = list(rows[0].keys()) if rows else []

        limit = int(spec.get("limit", 50))
        offset = int(spec.get("offset", 0))

        return {
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
