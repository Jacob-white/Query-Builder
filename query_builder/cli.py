"""
Command-Line Interface for Query Builder Engine.
================================================
Provides developer CLI utilities for compiling declarative specs to SQL,
validating raw SQL and query specs against AST safety rules, inspecting connectors,
testing database connectivity, and exporting schemas to Prisma, Drizzle, and SQLAlchemy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

from query_builder import __version__
from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.join_solver import find_join_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="query-builder",
        description="Universal SQL Query Builder, Declarative Compiler, AST Safety Validator & Schema Exporter.",
    )
    parser.add_argument(
        "--version", action="version", version=f"query-builder {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Compile subcommand
    compile_p = subparsers.add_parser(
        "compile", help="Compile a JSON query spec into parameterized SQL."
    )
    compile_p.add_argument(
        "--spec",
        "-s",
        required=True,
        help="Path to JSON query specification file or JSON string.",
    )
    compile_p.add_argument(
        "--schema", help="Optional path to JSON schema snapshot file."
    )
    compile_p.add_argument(
        "--dialect",
        "-d",
        default="postgres",
        help="SQL dialect (postgres, snowflake, mssql, sqlite, mysql).",
    )
    compile_p.add_argument(
        "--user-id",
        help="Optional user ID for ownership isolation.",
    )
    compile_p.add_argument(
        "--tenant-id",
        help="Optional tenant ID for multi-tenant isolation.",
    )
    compile_p.add_argument(
        "--output",
        "-o",
        help="Optional output file to write compiled SQL or JSON payload.",
    )
    compile_p.add_argument(
        "--json",
        action="store_true",
        help="Output compiled SQL and parameters as structured JSON.",
    )

    # 2. Validate subcommand
    validate_p = subparsers.add_parser(
        "validate",
        help="Validate a SQL query string or query spec against AST safety rules.",
    )
    validate_p.add_argument(
        "target", help="Raw SQL query string, .sql file, or .json query spec file."
    )
    validate_p.add_argument(
        "--allowed-schemas",
        help="Comma-separated list of authorized database schemas.",
    )
    validate_p.add_argument(
        "--restricted-tables",
        help="Comma-separated list of restricted table names.",
    )
    validate_p.add_argument(
        "--disallow-cte",
        action="store_true",
        help="Disallow Common Table Expressions (WITH queries).",
    )
    validate_p.add_argument(
        "--fail-on-risk",
        choices=["HIGH", "CRITICAL", "high", "critical"],
        help="Exit non-zero if injection risk meets or exceeds threshold (HIGH or CRITICAL).",
    )
    validate_p.add_argument(
        "--json",
        action="store_true",
        help="Output AST validation result as structured JSON.",
    )

    # 3. Test-connection subcommand
    test_p = subparsers.add_parser(
        "test-connection", help="Test database reachability and latency."
    )
    test_p.add_argument(
        "--connector",
        "-c",
        required=True,
        help="Registered connector identifier (e.g. sqlite, duckdb, postgres).",
    )
    test_p.add_argument(
        "--config", help="Connection configuration JSON string or file path."
    )
    test_p.add_argument(
        "--json",
        action="store_true",
        help="Output connection test status as structured JSON.",
    )

    # 4. Introspect subcommand
    introspect_p = subparsers.add_parser(
        "introspect", help="Reverse-engineer database schema metadata."
    )
    introspect_p.add_argument(
        "--connector",
        "-c",
        required=True,
        help="Registered connector identifier.",
    )
    introspect_p.add_argument(
        "--config", help="Connection configuration JSON string or file path."
    )
    introspect_p.add_argument(
        "--output",
        "-o",
        help="Optional output file path to write schema snapshot JSON.",
    )
    introspect_p.add_argument(
        "--filter-sensitive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Filter sensitive system and auth tables (default: enabled).",
    )
    introspect_p.add_argument(
        "--json",
        action="store_true",
        help="Output schema snapshot as structured JSON to stdout.",
    )

    # 5. Export-schema subcommand
    export_p = subparsers.add_parser(
        "export-schema", help="Convert schema snapshot into ORM schema definitions."
    )
    export_p.add_argument(
        "--schema",
        "-s",
        required=True,
        help="Path to schema snapshot JSON file or JSON string.",
    )
    export_p.add_argument(
        "--format",
        "-f",
        required=True,
        help="Target ORM schema format (prisma, drizzle, sqlalchemy).",
    )
    export_p.add_argument(
        "--dialect",
        "-d",
        help="Database dialect/provider (e.g. postgres, sqlite, mysql).",
    )
    export_p.add_argument(
        "--output",
        "-o",
        help="Optional output file path to write generated code.",
    )
    export_p.add_argument(
        "--json",
        action="store_true",
        help="Output export payload as structured JSON.",
    )

    # 6. Join path subcommand
    join_p = subparsers.add_parser(
        "join-path", help="Find the shortest join path between tables."
    )
    join_p.add_argument(
        "--active",
        "-a",
        required=True,
        help="Comma-separated list of active table names.",
    )
    join_p.add_argument(
        "--target", "-t", required=True, help="Target table name to join."
    )
    join_p.add_argument("--schema", help="Optional path to JSON schema snapshot file.")
    join_p.add_argument(
        "--json",
        action="store_true",
        help="Output join path as structured JSON.",
    )

    # 7. Serve subcommand
    serve_p = subparsers.add_parser(
        "serve", help="Start the Query-Builder HTTP API microservice."
    )
    serve_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind HTTP server (default: 127.0.0.1).",
    )
    serve_p.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000).",
    )

    args = parser.parse_args(argv)

    if args.command == "compile":
        try:
            if args.spec.startswith("{"):
                spec_data = json.loads(args.spec)
            else:
                with open(args.spec, "r", encoding="utf-8") as f:
                    spec_data = json.load(f)

            schema_data = None
            if args.schema:
                with open(args.schema, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)

            compiler = QueryCompiler(
                spec_data,
                schema=schema_data,
                dialect=args.dialect,
                user_id=getattr(args, "user_id", None),
                force_user_filter=bool(getattr(args, "user_id", None)),
                tenant_id=getattr(args, "tenant_id", None),
            )
            main_sql, params, count_sql, count_params = compiler.compile()

            if getattr(args, "json", False):
                payload = {
                    "main_sql": main_sql,
                    "params": params,
                    "count_sql": count_sql,
                    "count_params": count_params,
                    "dialect": args.dialect,
                }
                out_str = json.dumps(payload, indent=2)
                if args.output:
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(out_str)
                print(out_str)
            else:
                out_text = (
                    f"--- Main SQL ---\n{main_sql}\n\n"
                    f"--- Bind Parameters ---\n{params}\n\n"
                    f"--- Count Subquery ---\n{count_sql}"
                )
                if args.output:
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(main_sql)
                print(out_text)
            return 0
        except (CompilationError, json.JSONDecodeError, OSError) as e:
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Compilation error: {e}\n")
            return 1

    elif args.command == "validate":
        target = getattr(args, "target", None) or getattr(args, "sql", None)
        if not target:
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "violations": ["No query provided."],
                            "injection_risk": "NONE",
                        },
                        indent=2,
                    )
                )
            else:
                sys.stderr.write("Validation error: No query target provided.\n")
            return 1

        # Check for nonexistent file if target looks like a path
        if target.endswith((".json", ".sql")) and not os.path.exists(target):
            err_msg = f"Target file not found: {target}"
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "violations": [err_msg],
                            "injection_risk": "CRITICAL",
                        },
                        indent=2,
                    )
                )
            else:
                sys.stderr.write(f"Validation error: {err_msg}\n")
            return 1

        allowed_schemas = None
        if args.allowed_schemas:
            allowed_schemas = [
                s.strip() for s in args.allowed_schemas.split(",") if s.strip()
            ] + [
                s.strip().upper() for s in args.allowed_schemas.split(",") if s.strip()
            ]

        restricted_tables = None
        if args.restricted_tables:
            raw_t = [t.strip() for t in args.restricted_tables.split(",") if t.strip()]
            restricted_tables = set(raw_t) | {t.upper() for t in raw_t}

        allow_cte = not args.disallow_cte

        try:
            if os.path.isfile(target):
                if target.endswith(".json"):
                    with open(target, "r", encoding="utf-8") as f:
                        spec_data = json.load(f)
                    if (
                        isinstance(spec_data, dict)
                        and "sql" in spec_data
                        and "table" not in spec_data
                    ):
                        raw_sql = spec_data["sql"]
                    else:
                        compiler = QueryCompiler(spec_data)
                        raw_sql, _, _, _ = compiler.compile()
                else:
                    with open(target, "r", encoding="utf-8") as f:
                        raw_sql = f.read()
            elif target.startswith("{"):
                spec_data = json.loads(target)
                if (
                    isinstance(spec_data, dict)
                    and "sql" in spec_data
                    and "table" not in spec_data
                ):
                    raw_sql = spec_data["sql"]
                else:
                    compiler = QueryCompiler(spec_data)
                    raw_sql, _, _, _ = compiler.compile()
            else:
                raw_sql = target
        except Exception as exc:  # noqa: BLE001
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "violations": [f"Failed to load or compile target: {exc}"],
                            "injection_risk": "CRITICAL",
                        },
                        indent=2,
                    )
                )
            else:
                sys.stderr.write(f"Validation error: {exc}\n")
            return 1

        res = validate_sql_ast(
            raw_sql,
            allowed_schemas=allowed_schemas,
            restricted_tables=restricted_tables,
            allow_cte=allow_cte,
        )

        risk = res.get("injection_risk", "NONE").upper()
        risk_failed = False
        if args.fail_on_risk:
            thresh = args.fail_on_risk.upper()
            if (thresh == "HIGH" and risk in ("HIGH", "CRITICAL")) or (
                thresh == "CRITICAL" and risk == "CRITICAL"
            ):
                risk_failed = True

        is_valid = bool(res.get("valid", False)) and not risk_failed

        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            if is_valid:
                print("[PASS] AST validation succeeded. Safe read-only SELECT query.")
            else:
                print("[FAIL] AST validation failed:")
                print(f"  Statement type: {res.get('statement_type', 'UNKNOWN')}")
                print(f"  Injection risk: {res.get('injection_risk', 'UNKNOWN')}")
                violations = list(res.get("violations", []))
                if risk_failed:
                    violations.append(
                        f"Risk level {risk} meets or exceeds threshold {args.fail_on_risk}"
                    )
                print("  Violations:")
                for v in violations:
                    print(f"    - {v}")

        return 0 if is_valid else 1

    elif args.command == "test-connection":
        try:
            config: dict[str, Any] = {}
            if args.config:
                if os.path.isfile(args.config):
                    with open(args.config, "r", encoding="utf-8") as f:
                        config = json.load(f)
                else:
                    config = json.loads(args.config)

            from query_builder.connectors import AsyncBaseConnector, ConnectorRegistry

            connector = ConnectorRegistry.get(args.connector, **config)

            if isinstance(connector, AsyncBaseConnector):
                result = asyncio.run(connector.test_connection())
            else:
                result = connector.test_connection()

            is_ok = result.get("status") == "healthy" or result.get("success") is True

            if getattr(args, "json", False):
                print(json.dumps(result, indent=2))
            else:
                if is_ok:
                    latency = result.get("latency_ms", "N/A")
                    dialect = result.get("dialect", args.connector)
                    print(
                        f"[OK] Connection to '{args.connector}' successful (dialect: {dialect}, latency: {latency}ms)"
                    )
                else:
                    err = result.get("error", "Health check failed")
                    print(f"[ERROR] Connection to '{args.connector}' failed: {err}")
            return 0 if is_ok else 1

        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"success": False, "status": "unhealthy", "error": str(e)},
                        indent=2,
                    )
                )
            else:
                print(f"[ERROR] Connection to '{args.connector}' failed: {e}")
            return 1

    elif args.command == "introspect":
        try:
            config = {}
            if args.config:
                if os.path.isfile(args.config):
                    with open(args.config, "r", encoding="utf-8") as f:
                        config = json.load(f)
                else:
                    config = json.loads(args.config)

            from query_builder.connectors import AsyncBaseConnector, ConnectorRegistry

            connector = ConnectorRegistry.get(args.connector, **config)

            filter_sensitive = bool(getattr(args, "filter_sensitive", True))

            if isinstance(connector, AsyncBaseConnector):
                snapshot = asyncio.run(
                    connector.introspect_schema(filter_sensitive=filter_sensitive)
                )
            else:
                snapshot = connector.introspect_schema(
                    filter_sensitive=filter_sensitive
                )

            if is_dataclass(snapshot):
                snap_dict = asdict(snapshot)
            elif isinstance(snapshot, dict):
                snap_dict = snapshot
            else:
                snap_dict = {"tables": {}}

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(snap_dict, f, indent=2)

            if getattr(args, "json", False):
                print(json.dumps(snap_dict, indent=2))
            else:
                tables = snap_dict.get("tables", {})
                table_count = len(tables)
                col_count = sum(
                    len(t.get("columns", []))
                    for t in (tables.values() if isinstance(tables, dict) else [])
                )
                print(
                    f"[OK] Introspected {table_count} tables ({col_count} columns) from '{args.connector}'."
                )
                if table_count > 0:
                    sorted_tables = sorted(tables.keys())
                    print(f"  Tables: {', '.join(sorted_tables)}")
            return 0

        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Introspection error: {e}\n")
            return 1

    elif args.command == "export-schema":
        try:
            if args.schema.startswith("{"):
                schema_data = json.loads(args.schema)
            else:
                with open(args.schema, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)

            fmt = args.format.lower().strip()
            dialect = args.dialect

            from query_builder.schema_converters import (
                to_drizzle_schema,
                to_prisma_schema,
                to_sqlalchemy_models,
            )

            if fmt == "prisma":
                provider = dialect or "postgresql"
                content = to_prisma_schema(schema_data, provider=provider)
                used_dialect = provider
            elif fmt == "drizzle":
                d_dialect = dialect or "postgres"
                content = to_drizzle_schema(schema_data, dialect=d_dialect)
                used_dialect = d_dialect
            elif fmt == "sqlalchemy":
                content = to_sqlalchemy_models(schema_data)
                used_dialect = dialect or "sqlalchemy"
            else:
                raise ValueError(
                    f"Unknown format '{fmt}'. Choose from: prisma, drizzle, sqlalchemy"
                )

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(content)

            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "success": True,
                            "format": fmt,
                            "dialect": used_dialect,
                            "content": content,
                        },
                        indent=2,
                    )
                )
            else:
                if args.output:
                    print(f"[OK] Exported {fmt} schema to {args.output}")
                else:
                    print(content)
            return 0

        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Export error: {e}\n")
            return 1

    elif args.command == "join-path":
        try:
            active = [t.strip() for t in args.active.split(",") if t.strip()]
            schema_data = None
            if args.schema:
                with open(args.schema, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)

            path = find_join_path(active, args.target, schema_data)
            print(json.dumps(path, indent=2))
            return 0
        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Join path error: {e}\n")
            return 1

    else:
        from query_builder.server import create_server

        server = create_server(host=args.host, port=args.port)
        actual_port = server.server_address[1]
        sys.stdout.write(
            f"Query Builder server listening on http://{args.host}:{actual_port} (Docs: http://{args.host}:{actual_port}/docs)\n"
        )
        sys.stdout.flush()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            sys.stdout.write("\nShutting down server...\n")
            server.server_close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
